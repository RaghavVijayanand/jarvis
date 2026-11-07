"""
Advanced System Monitoring Skill for JARVIS
Provides detailed system insights, performance tracking, and health monitoring
"""

import psutil
import time
import json
import os
import platform
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import wmi
import socket


class SystemMonitor:
    @staticmethod
    def _system_drive() -> str:
        """Root of the Windows system drive (not always C:), or '/' elsewhere."""
        if os.name == 'nt':
            return os.environ.get('SystemDrive', 'C:').rstrip('\\') + '\\'
        return '/'

    @staticmethod
    def _percent(usage) -> float:
        """Disk usage percent without dividing by zero for empty/virtual volumes."""
        return (usage.used / usage.total * 100) if usage.total else 0.0

    def __init__(self):
        """Initialize system monitoring"""
        self.monitoring_data = {}
        from core.config import Config
        self.alerts_file = str(Config.DATA_DIR / "system_alerts.json")
        self.wmi_available = True
        
        try:
            self.wmi_interface = wmi.WMI()
        except Exception:
            self.wmi_available = False
        
        # Performance thresholds
        self.thresholds = {
            'cpu_warning': 80,
            'cpu_critical': 95,
            'memory_warning': 80,
            'memory_critical': 90,
            'disk_warning': 85,
            'disk_critical': 95,
            'temp_warning': 70,
            'temp_critical': 85
        }
    
    def _wmi(self, namespace: Optional[str] = None):
        """Open a WMI connection on the *calling* thread.

        COM objects are apartment-bound: the connection made in __init__ (GUI
        thread) raises "marshalled for a different thread" when reused from a
        QThread worker, so every query opens its own connection after
        CoInitialize()."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        return wmi.WMI(namespace=namespace) if namespace else wmi.WMI()

    def get_cpu_info(self) -> Dict:
        """Get CPU usage information"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()
            
            return {
                'usage': cpu_percent,
                'cores': cpu_count,
                'frequency': cpu_freq.current if cpu_freq else 0
            }
        except Exception as e:
            return {'usage': 0, 'cores': 0, 'frequency': 0, 'error': str(e)}
    
    def get_memory_info(self) -> Dict:
        """Get memory usage information"""
        try:
            memory = psutil.virtual_memory()
            
            return {
                'total_gb': memory.total / (1024**3),
                'used_gb': memory.used / (1024**3),
                'available_gb': memory.available / (1024**3),
                'percentage': memory.percent
            }
        except Exception as e:
            return {'total_gb': 0, 'used_gb': 0, 'available_gb': 0, 'percentage': 0, 'error': str(e)}
    
    def get_system_info(self) -> str:
        """Get basic system information for quick reference"""
        try:
            # Get current system stats
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            
            # Disk usage of the system drive
            try:
                disk_percent = self._percent(psutil.disk_usage(self._system_drive()))
            except Exception:
                disk_percent = 0
            
            # Get system uptime
            boot_time = psutil.boot_time()
            uptime = datetime.now() - datetime.fromtimestamp(boot_time)
            
            # Format uptime nicely
            days = uptime.days
            hours, remainder = divmod(uptime.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            uptime_str = f"{days}d {hours}h {minutes}m"
            
            info = f"""CPU Usage: {cpu_percent}%
Memory Usage: {memory.percent}% ({self._format_bytes(memory.used)}/{self._format_bytes(memory.total)})
Disk Usage: {disk_percent:.1f}%
Uptime: {uptime_str}
Processes: {len(psutil.pids())}"""
            
            return info
            
        except Exception as e:
            return f"Error getting system info: {str(e)}"
    
    def get_performance_metrics(self) -> Dict:
        """Get current performance metrics"""
        try:
            # One 1-second sample serves both the total and per-core figures
            # (previously two back-to-back blocking samples).
            per_core = psutil.cpu_percent(interval=1, percpu=True) or []
            cpu_freq = psutil.cpu_freq()
            metrics = {
                'timestamp': datetime.now().isoformat(),
                'cpu': {
                    'usage_percent': (sum(per_core) / len(per_core)) if per_core else psutil.cpu_percent(interval=None),
                    'usage_per_core': per_core,
                    'frequency': cpu_freq._asdict() if cpu_freq else None,
                    'load_average': os.getloadavg() if hasattr(os, 'getloadavg') else None
                },
                'memory': {
                    'virtual': psutil.virtual_memory()._asdict(),
                    'swap': psutil.swap_memory()._asdict()
                },
                'disk': {},
                'network': {},
                'processes': self._get_top_processes()
            }
            
            # Disk I/O
            disk_io = psutil.disk_io_counters()
            if disk_io:
                metrics['disk']['io'] = disk_io._asdict()
            
            # Disk usage for each partition
            for partition in psutil.disk_partitions():
                opts = (partition.opts or '').split(',')
                # An inserted DVD (opts "cdrom") or read-only image is always
                # "100% full"; don't raise critical disk alerts for it.
                if 'cdrom' in opts or 'ro' in opts:
                    continue
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    metrics['disk'][partition.device] = {
                        'total': usage.total,
                        'used': usage.used,
                        'free': usage.free,
                        'percent': self._percent(usage)
                    }
                except Exception:  # empty card reader / CD drive, access denied
                    continue
            
            # Network I/O
            net_io = psutil.net_io_counters()
            if net_io:
                metrics['network']['io'] = net_io._asdict()
            
            # Network connections (may need elevation on some systems)
            try:
                metrics['network']['connections'] = len(psutil.net_connections())
            except (psutil.AccessDenied, OSError):
                pass
            
            return metrics
            
        except Exception as e:
            return {'error': str(e)}
    
    def _get_top_processes(self, limit: int = 10) -> List[Dict]:
        """Get top processes by CPU usage"""
        try:
            # Process.cpu_percent() returns a meaningless 0.0 on its first call,
            # so prime every process, wait, then read the real figure.
            procs = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_percent', 'status']):
                try:
                    if proc.info.get('pid') == 0:  # Windows "System Idle Process"
                        continue
                    proc.cpu_percent(None)
                    procs.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            time.sleep(0.5)
            cores = psutil.cpu_count() or 1
            processes = []
            for proc in procs:
                try:
                    proc_info = dict(proc.info)
                    proc_info['name'] = proc_info.get('name') or f"PID {proc_info.get('pid')}"
                    # Normalise to 0-100% of the whole machine (Task Manager style).
                    proc_info['cpu_percent'] = (proc.cpu_percent(None) or 0.0) / cores
                    processes.append(proc_info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            processes.sort(key=lambda x: x.get('cpu_percent') or 0, reverse=True)
            return processes[:limit]
            
        except Exception:
            return []
    
    def check_system_health(self) -> str:
        """Perform comprehensive system health check"""
        try:
            health_report = []
            alerts = []
            
            # Get current metrics
            metrics = self.get_performance_metrics()
            
            if 'error' in metrics:
                return f"Error getting system metrics: {metrics['error']}"
            
            health_report.append("=== SYSTEM HEALTH CHECK ===")
            health_report.append(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            health_report.append("")
            
            # CPU Health
            cpu_usage = metrics['cpu']['usage_percent']
            health_report.append(f"CPU Usage: {cpu_usage:.1f}%")
            
            if cpu_usage > self.thresholds['cpu_critical']:
                alerts.append(f"🔴 CRITICAL: CPU usage is very high ({cpu_usage:.1f}%)")
                health_report.append("  Status: 🔴 CRITICAL")
            elif cpu_usage > self.thresholds['cpu_warning']:
                alerts.append(f"🟡 WARNING: CPU usage is high ({cpu_usage:.1f}%)")
                health_report.append("  Status: 🟡 WARNING")
            else:
                health_report.append("  Status: ✅ GOOD")
            
            # Memory Health
            memory_percent = metrics['memory']['virtual']['percent']
            memory_available = self._format_bytes(metrics['memory']['virtual']['available'])
            health_report.append(f"Memory Usage: {memory_percent:.1f}% (Available: {memory_available})")
            
            if memory_percent > self.thresholds['memory_critical']:
                alerts.append(f"🔴 CRITICAL: Memory usage is very high ({memory_percent:.1f}%)")
                health_report.append("  Status: 🔴 CRITICAL")
            elif memory_percent > self.thresholds['memory_warning']:
                alerts.append(f"🟡 WARNING: Memory usage is high ({memory_percent:.1f}%)")
                health_report.append("  Status: 🟡 WARNING")
            else:
                health_report.append("  Status: ✅ GOOD")
            
            # Disk Health
            health_report.append("Disk Usage:")
            for device, usage in metrics['disk'].items():
                if device == 'io':
                    continue
                
                disk_percent = usage['percent']
                disk_free = self._format_bytes(usage['free'])
                health_report.append(f"  {device}: {disk_percent:.1f}% (Free: {disk_free})")
                
                if disk_percent > self.thresholds['disk_critical']:
                    alerts.append(f"🔴 CRITICAL: Disk {device} is almost full ({disk_percent:.1f}%)")
                elif disk_percent > self.thresholds['disk_warning']:
                    alerts.append(f"🟡 WARNING: Disk {device} is getting full ({disk_percent:.1f}%)")
            
            # Process Health
            health_report.append("Top CPU Processes:")
            for proc in metrics['processes'][:5]:
                health_report.append(f"  {proc['name']} (PID: {proc['pid']}): {proc.get('cpu_percent', 0):.1f}% CPU")
            
            # Network Health
            if 'connections' in metrics['network']:
                conn_count = metrics['network']['connections']
                health_report.append(f"Network Connections: {conn_count}")
                
                if conn_count > 1000:
                    alerts.append(f"🟡 WARNING: High number of network connections ({conn_count})")
            
            # Temperature (Windows specific)
            if self.wmi_available:
                try:
                    temp_info = self._get_temperature_info()
                    if temp_info:
                        health_report.append("System Temperature:")
                        health_report.append(f"  {temp_info}")
                except Exception:
                    pass
            
            # Uptime
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot_time
            health_report.append(f"System Uptime: {self._format_timedelta(uptime)}")
            
            # Overall health status
            if alerts:
                health_report.append("\n=== ALERTS ===")
                for alert in alerts:
                    health_report.append(alert)
                
                # Save alerts
                self._save_alerts(alerts)
            else:
                health_report.append("\n✅ System health is GOOD - No issues detected")
            
            return "\n".join(health_report)
            
        except Exception as e:
            return f"Error performing health check: {e}"
    
    def get_hardware_info(self) -> str:
        """Get detailed hardware information"""
        try:
            hardware_info = []
            
            if not self.wmi_available:
                return "WMI not available - limited hardware information possible"

            conn = self._wmi()
            hardware_info.append("=== HARDWARE INFORMATION ===")
            
            # CPU Information
            hardware_info.append("\n--- CPU ---")
            for cpu in conn.Win32_Processor():
                hardware_info.append(f"Name: {cpu.Name}")
                hardware_info.append(f"Manufacturer: {cpu.Manufacturer}")
                hardware_info.append(f"Architecture: {cpu.Architecture}")
                hardware_info.append(f"Max Clock Speed: {cpu.MaxClockSpeed} MHz")
                hardware_info.append(f"Cores: {cpu.NumberOfCores}")
                hardware_info.append(f"Logical Processors: {cpu.NumberOfLogicalProcessors}")
                hardware_info.append(f"Socket: {cpu.SocketDesignation}")
            
            # Memory Information
            hardware_info.append("\n--- MEMORY ---")
            total_capacity = 0
            for memory in conn.Win32_PhysicalMemory():
                capacity_gb = int(memory.Capacity or 0) / (1024**3)
                total_capacity += capacity_gb
                hardware_info.append(f"Capacity: {capacity_gb:.1f} GB")
                hardware_info.append(f"Speed: {memory.Speed} MHz")
                hardware_info.append(f"Manufacturer: {memory.Manufacturer}")
                hardware_info.append(f"Part Number: {memory.PartNumber}")
                hardware_info.append(f"Location: {memory.DeviceLocator}")
                hardware_info.append("")
            
            hardware_info.append(f"Total RAM: {total_capacity:.1f} GB")
            
            # Motherboard Information
            hardware_info.append("\n--- MOTHERBOARD ---")
            for board in conn.Win32_BaseBoard():
                hardware_info.append(f"Manufacturer: {board.Manufacturer}")
                hardware_info.append(f"Product: {board.Product}")
                hardware_info.append(f"Version: {board.Version}")
                hardware_info.append(f"Serial Number: {board.SerialNumber}")
            
            # Graphics Information
            hardware_info.append("\n--- GRAPHICS ---")
            for gpu in conn.Win32_VideoController():
                if gpu.Name:
                    hardware_info.append(f"Name: {gpu.Name}")
                    if gpu.AdapterRAM:
                        vram_gb = int(gpu.AdapterRAM) / (1024**3)
                        hardware_info.append(f"VRAM: {vram_gb:.1f} GB")
                    hardware_info.append(f"Driver Version: {gpu.DriverVersion}")
                    hardware_info.append("")
            
            # Storage Information
            hardware_info.append("--- STORAGE ---")
            for disk in conn.Win32_DiskDrive():
                if disk.Size:
                    size_gb = int(disk.Size) / (1024**3)
                    hardware_info.append(f"Model: {disk.Model}")
                    hardware_info.append(f"Size: {size_gb:.1f} GB")
                    hardware_info.append(f"Interface: {disk.InterfaceType}")
                    hardware_info.append(f"Media Type: {disk.MediaType}")
                    hardware_info.append("")
            
            return "\n".join(hardware_info)
            
        except Exception as e:
            return f"Error getting hardware information: {e}"
    
    def _get_temperature_info(self) -> Optional[str]:
        """Get system temperature information (Windows)"""
        try:
            if not self.wmi_available:
                return None
            
            temps = []
            # MSAcpi_ThermalZoneTemperature lives in root\\wmi, not the default
            # root\\cimv2 namespace (and usually needs an elevated process).
            for temp_sensor in self._wmi(namespace="root\\wmi").MSAcpi_ThermalZoneTemperature():
                if not temp_sensor.CurrentTemperature:
                    continue
                # Convert from tenths of Kelvin to Celsius
                temp_celsius = temp_sensor.CurrentTemperature / 10.0 - 273.15
                temps.append(f"{temp_celsius:.1f}°C")

            if temps:
                return " | ".join(temps)

        except Exception:
            pass
        
        return None
    
    def _format_bytes(self, bytes_value: int) -> str:
        """Format bytes to human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.1f} PB"
    
    def _format_timedelta(self, td: timedelta) -> str:
        """Format timedelta to human readable format"""
        days = td.days
        hours, remainder = divmod(td.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        
        return ", ".join(parts) if parts else "Less than a minute"
    
    def _save_alerts(self, alerts: List[str]):
        """Save system alerts to file"""
        try:
            alert_data = {
                'timestamp': datetime.now().isoformat(),
                'alerts': alerts
            }
            
            # Load existing alerts
            existing_alerts = []
            if os.path.exists(self.alerts_file):
                try:
                    with open(self.alerts_file, 'r', encoding='utf-8') as f:
                        existing_alerts = json.load(f)
                except (OSError, ValueError):
                    existing_alerts = []  # corrupt log: start over, don't fail forever
                if not isinstance(existing_alerts, list):
                    existing_alerts = []
            
            # Add new alerts
            existing_alerts.append(alert_data)
            
            # Keep only last 100 alerts
            existing_alerts = existing_alerts[-100:]
            
            # Save back to file
            with open(self.alerts_file, 'w', encoding='utf-8') as f:
                json.dump(existing_alerts, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            print(f"Error saving alerts: {e}")
    
    def get_network_analysis(self) -> str:
        """Get detailed network analysis"""
        try:
            analysis = []
            analysis.append("=== NETWORK ANALYSIS ===")
            
            # Active connections
            try:
                connections = psutil.net_connections()
            except (psutil.AccessDenied, OSError):
                connections = []
                analysis.append("(Connection list unavailable - access denied)")
            tcp_count = sum(1 for conn in connections if conn.type == socket.SOCK_STREAM)
            udp_count = sum(1 for conn in connections if conn.type == socket.SOCK_DGRAM)
            
            analysis.append(f"Active Connections: {len(connections)}")
            analysis.append(f"  TCP: {tcp_count}")
            analysis.append(f"  UDP: {udp_count}")
            
            # Connection states (UDP sockets report the placeholder "NONE")
            states = {}
            for conn in connections:
                if getattr(conn, 'status', None) and conn.status != psutil.CONN_NONE:
                    states[conn.status] = states.get(conn.status, 0) + 1
            
            if states:
                analysis.append("Connection States:")
                for state, count in sorted(states.items()):
                    analysis.append(f"  {state}: {count}")
            
            # Network interfaces
            interfaces = psutil.net_if_stats()
            analysis.append("\nNetwork Interfaces:")
            for interface, stats in interfaces.items():
                analysis.append(f"  {interface}:")
                analysis.append(f"    Status: {'UP' if stats.isup else 'DOWN'}")
                analysis.append(f"    Speed: {stats.speed} Mbps" if stats.speed > 0 else "    Speed: Unknown")
                analysis.append(f"    MTU: {stats.mtu}")
            
            # Network I/O
            net_io = psutil.net_io_counters()
            if net_io:
                analysis.append("\nNetwork I/O:")
                analysis.append(f"  Bytes Sent: {self._format_bytes(net_io.bytes_sent)}")
                analysis.append(f"  Bytes Received: {self._format_bytes(net_io.bytes_recv)}")
                analysis.append(f"  Packets Sent: {net_io.packets_sent:,}")
                analysis.append(f"  Packets Received: {net_io.packets_recv:,}")
                
                if net_io.errin > 0 or net_io.errout > 0:
                    analysis.append(f"  Errors In: {net_io.errin}")
                    analysis.append(f"  Errors Out: {net_io.errout}")
                
                if net_io.dropin > 0 or net_io.dropout > 0:
                    analysis.append(f"  Dropped In: {net_io.dropin}")
                    analysis.append(f"  Dropped Out: {net_io.dropout}")
            
            return "\n".join(analysis)
            
        except Exception as e:
            return f"Error analyzing network: {e}"
