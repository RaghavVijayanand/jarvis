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
    def __init__(self):
        """Initialize system monitoring"""
        self.monitoring_data = {}
        self.alerts_file = "system_alerts.json"
        self.performance_log = "performance_log.json"
        self.wmi_available = True
        
        try:
            self.wmi_interface = wmi.WMI()
        except:
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
    
    def get_system_info(self) -> str:
        """Get basic system information for quick reference"""
        try:
            # Get current system stats
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            
            # Get disk usage for Windows (use C:)
            try:
                disk_usage = psutil.disk_usage('C:' if os.name == 'nt' else '/')
                disk_percent = (disk_usage.used / disk_usage.total * 100)
            except:
                disk_percent = 0
                disk_usage = None
            
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
    
    def _format_bytes(self, bytes_value):
        """Format bytes to human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.2f} PB"
    
    def get_detailed_system_info(self) -> str:
        """Get comprehensive system information"""
        try:
            info = []
            
            # Basic system info
            info.append("=== SYSTEM INFORMATION ===")
            info.append(f"OS: {platform.system()} {platform.release()}")
            info.append(f"Architecture: {platform.architecture()[0]}")
            info.append(f"Processor: {platform.processor()}")
            info.append(f"Machine: {platform.machine()}")
            info.append(f"Node: {platform.node()}")
            
            # CPU Information
            info.append("\n=== CPU INFORMATION ===")
            info.append(f"Physical cores: {psutil.cpu_count(logical=False)}")
            info.append(f"Total cores: {psutil.cpu_count(logical=True)}")
            
            # Get CPU frequencies
            cpu_freq = psutil.cpu_freq()
            if cpu_freq:
                info.append(f"Max Frequency: {cpu_freq.max:.2f}Mhz")
                info.append(f"Min Frequency: {cpu_freq.min:.2f}Mhz")
                info.append(f"Current Frequency: {cpu_freq.current:.2f}Mhz")
            
            # CPU usage per core
            cpu_usage = psutil.cpu_percent(interval=1, percpu=True)
            info.append("CPU Usage Per Core:")
            for i, percentage in enumerate(cpu_usage):
                info.append(f"  Core {i}: {percentage}%")
            
            # Memory Information
            info.append("\n=== MEMORY INFORMATION ===")
            memory = psutil.virtual_memory()
            info.append(f"Total: {self._format_bytes(memory.total)}")
            info.append(f"Available: {self._format_bytes(memory.available)}")
            info.append(f"Used: {self._format_bytes(memory.used)} ({memory.percent}%)")
            info.append(f"Free: {self._format_bytes(memory.free)}")
            
            # Swap memory
            swap = psutil.swap_memory()
            if swap.total > 0:
                info.append(f"Swap Total: {self._format_bytes(swap.total)}")
                info.append(f"Swap Used: {self._format_bytes(swap.used)} ({swap.percent}%)")
            
            # Disk Information
            info.append("\n=== DISK INFORMATION ===")
            partitions = psutil.disk_partitions()
            for partition in partitions:
                info.append(f"Device: {partition.device}")
                info.append(f"  Mountpoint: {partition.mountpoint}")
                info.append(f"  File system: {partition.fstype}")
                
                try:
                    partition_usage = psutil.disk_usage(partition.mountpoint)
                    info.append(f"  Total Size: {self._format_bytes(partition_usage.total)}")
                    info.append(f"  Used: {self._format_bytes(partition_usage.used)}")
                    info.append(f"  Free: {self._format_bytes(partition_usage.free)}")
                    info.append(f"  Percentage: {partition_usage.used / partition_usage.total * 100:.1f}%")
                except PermissionError:
                    info.append("  Permission Denied")
                info.append("")
            
            # Network Information
            info.append("=== NETWORK INFORMATION ===")
            network_info = psutil.net_if_addrs()
            for interface_name, interface_addresses in network_info.items():
                info.append(f"Interface: {interface_name}")
                for address in interface_addresses:
                    if str(address.family) == 'AddressFamily.AF_INET':
                        info.append(f"  IP Address: {address.address}")
                        info.append(f"  Netmask: {address.netmask}")
                        info.append(f"  Broadcast IP: {address.broadcast}")
                    elif str(address.family) == 'AddressFamily.AF_PACKET':
                        info.append(f"  MAC Address: {address.address}")
                        info.append(f"  Netmask: {address.netmask}")
                        info.append(f"  Broadcast MAC: {address.broadcast}")
                info.append("")
            
            return "\n".join(info)
            
        except Exception as e:
            return f"Error getting system information: {e}"
    
    def get_performance_metrics(self) -> Dict:
        """Get current performance metrics"""
        try:
            metrics = {
                'timestamp': datetime.now().isoformat(),
                'cpu': {
                    'usage_percent': psutil.cpu_percent(interval=1),
                    'usage_per_core': psutil.cpu_percent(interval=1, percpu=True),
                    'frequency': psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
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
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    metrics['disk'][partition.device] = {
                        'total': usage.total,
                        'used': usage.used,
                        'free': usage.free,
                        'percent': (usage.used / usage.total) * 100
                    }
                except:
                    continue
            
            # Network I/O
            net_io = psutil.net_io_counters()
            if net_io:
                metrics['network']['io'] = net_io._asdict()
            
            # Network connections
            connections = len(psutil.net_connections())
            metrics['network']['connections'] = connections
            
            return metrics
            
        except Exception as e:
            return {'error': str(e)}
    
    def _get_top_processes(self, limit: int = 10) -> List[Dict]:
        """Get top processes by CPU usage"""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
                try:
                    proc_info = proc.info
                    proc_info['cpu_percent'] = proc.cpu_percent()
                    processes.append(proc_info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Sort by CPU usage
            processes.sort(key=lambda x: x.get('cpu_percent', 0), reverse=True)
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
                except:
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
            
            hardware_info.append("=== HARDWARE INFORMATION ===")
            
            # CPU Information
            hardware_info.append("\n--- CPU ---")
            for cpu in self.wmi_interface.Win32_Processor():
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
            for memory in self.wmi_interface.Win32_PhysicalMemory():
                capacity_gb = int(memory.Capacity) / (1024**3)
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
            for board in self.wmi_interface.Win32_BaseBoard():
                hardware_info.append(f"Manufacturer: {board.Manufacturer}")
                hardware_info.append(f"Product: {board.Product}")
                hardware_info.append(f"Version: {board.Version}")
                hardware_info.append(f"Serial Number: {board.SerialNumber}")
            
            # Graphics Information
            hardware_info.append("\n--- GRAPHICS ---")
            for gpu in self.wmi_interface.Win32_VideoController():
                if gpu.Name:
                    hardware_info.append(f"Name: {gpu.Name}")
                    if gpu.AdapterRAM:
                        vram_gb = int(gpu.AdapterRAM) / (1024**3)
                        hardware_info.append(f"VRAM: {vram_gb:.1f} GB")
                    hardware_info.append(f"Driver Version: {gpu.DriverVersion}")
                    hardware_info.append("")
            
            # Storage Information
            hardware_info.append("--- STORAGE ---")
            for disk in self.wmi_interface.Win32_DiskDrive():
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
            for temp_sensor in self.wmi_interface.MSAcpi_ThermalZoneTemperature():
                # Convert from tenths of Kelvin to Celsius
                temp_celsius = temp_sensor.CurrentTemperature / 10.0 - 273.15
                temps.append(f"{temp_celsius:.1f}°C")
            
            if temps:
                return " | ".join(temps)
            
        except:
            pass
        
        return None
    
    def monitor_performance(self, duration_minutes: int = 5) -> str:
        """Monitor system performance over time"""
        try:
            samples = []
            interval = 30  # seconds
            total_samples = (duration_minutes * 60) // interval
            
            for i in range(total_samples):
                sample = {
                    'timestamp': datetime.now().isoformat(),
                    'cpu_percent': psutil.cpu_percent(interval=1),
                    'memory_percent': psutil.virtual_memory().percent,
                    'disk_usage': {}
                }
                
                # Sample disk usage for main drives
                for partition in psutil.disk_partitions()[:2]:  # Limit to first 2 drives
                    try:
                        usage = psutil.disk_usage(partition.mountpoint)
                        sample['disk_usage'][partition.device] = (usage.used / usage.total) * 100
                    except:
                        continue
                
                samples.append(sample)
                
                if i < total_samples - 1:  # Don't sleep on last iteration
                    time.sleep(interval)
            
            # Analyze samples
            if not samples:
                return "No performance data collected"
            
            avg_cpu = sum(s['cpu_percent'] for s in samples) / len(samples)
            max_cpu = max(s['cpu_percent'] for s in samples)
            avg_memory = sum(s['memory_percent'] for s in samples) / len(samples)
            max_memory = max(s['memory_percent'] for s in samples)
            
            report = []
            report.append(f"=== PERFORMANCE MONITORING REPORT ===")
            report.append(f"Duration: {duration_minutes} minutes")
            report.append(f"Samples: {len(samples)}")
            report.append("")
            report.append(f"CPU Usage:")
            report.append(f"  Average: {avg_cpu:.1f}%")
            report.append(f"  Maximum: {max_cpu:.1f}%")
            report.append("")
            report.append(f"Memory Usage:")
            report.append(f"  Average: {avg_memory:.1f}%")
            report.append(f"  Maximum: {max_memory:.1f}%")
            
            # Save detailed data
            log_data = {
                'timestamp': datetime.now().isoformat(),
                'duration_minutes': duration_minutes,
                'samples': samples,
                'summary': {
                    'avg_cpu': avg_cpu,
                    'max_cpu': max_cpu,
                    'avg_memory': avg_memory,
                    'max_memory': max_memory
                }
            }
            
            self._save_performance_log(log_data)
            
            return "\n".join(report)
            
        except Exception as e:
            return f"Error monitoring performance: {e}"
    
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
                with open(self.alerts_file, 'r') as f:
                    existing_alerts = json.load(f)
            
            # Add new alerts
            existing_alerts.append(alert_data)
            
            # Keep only last 100 alerts
            existing_alerts = existing_alerts[-100:]
            
            # Save back to file
            with open(self.alerts_file, 'w') as f:
                json.dump(existing_alerts, f, indent=2)
                
        except Exception as e:
            print(f"Error saving alerts: {e}")
    
    def _save_performance_log(self, log_data: Dict):
        """Save performance monitoring data"""
        try:
            # Load existing logs
            existing_logs = []
            if os.path.exists(self.performance_log):
                with open(self.performance_log, 'r') as f:
                    existing_logs = json.load(f)
            
            # Add new log
            existing_logs.append(log_data)
            
            # Keep only last 50 logs
            existing_logs = existing_logs[-50:]
            
            # Save back to file
            with open(self.performance_log, 'w') as f:
                json.dump(existing_logs, f, indent=2)
                
        except Exception as e:
            print(f"Error saving performance log: {e}")
    
    def get_network_analysis(self) -> str:
        """Get detailed network analysis"""
        try:
            analysis = []
            analysis.append("=== NETWORK ANALYSIS ===")
            
            # Active connections
            connections = psutil.net_connections()
            tcp_count = sum(1 for conn in connections if conn.type == socket.SOCK_STREAM)
            udp_count = sum(1 for conn in connections if conn.type == socket.SOCK_DGRAM)
            
            analysis.append(f"Active Connections: {len(connections)}")
            analysis.append(f"  TCP: {tcp_count}")
            analysis.append(f"  UDP: {udp_count}")
            
            # Connection states
            states = {}
            for conn in connections:
                if hasattr(conn, 'status'):
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
