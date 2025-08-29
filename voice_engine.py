import pyttsx3
import speech_recognition as sr
import threading
import time
import re
from config import Config
from rich.console import Console

console = Console()

class VoiceEngine:
    def __init__(self):
        # Initialize text-to-speech
        self.tts_engine = pyttsx3.init()
        self.setup_tts()
        
        # Initialize speech recognition
        try:
            self.recognizer = sr.Recognizer()
            # Default microphone (system default)
            self.microphone = sr.Microphone()
            self.mic_index = getattr(self.microphone, 'device_index', None)
            # Log selected microphone
            try:
                names = sr.Microphone.list_microphone_names()
                name = None
                if self.mic_index is not None and 0 <= self.mic_index < len(names):
                    name = names[self.mic_index]
                else:
                    # Resolve default device via PyAudio when index is None
                    pa = sr.Microphone.get_pyaudio()
                    try:
                        info = pa.get_default_input_device_info()
                        self.mic_index = info.get('index', None)
                        if self.mic_index is not None and 0 <= self.mic_index < len(names):
                            name = names[self.mic_index]
                        else:
                            name = info.get('name', 'Default Input Device')
                    finally:
                        # Terminate PyAudio instance to release resources
                        try:
                            pa.terminate()
                        except Exception:
                            pass
                if name:
                    console.print(f"[cyan]Using microphone: {name} (index: {self.mic_index if self.mic_index is not None else 'default'})[/cyan]")
            except Exception:
                pass
            self.sr_available = True
            self.calibrate_microphone()
            console.print("[green]✅ Voice recognition initialized[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠️ Voice recognition not available: {e}[/yellow]")
            self.sr_available = False
        
        # Audio processing
        self.is_speaking = False
        self.is_listening = False
        
    def setup_tts(self):
        """Configure text-to-speech engine for natural speech"""
        voices = self.tts_engine.getProperty('voices')
        
        # Try to find a more natural-sounding voice
        preferred_voices = [
            'david', 'mark', 'zira', 'hazel', 'susan', 'james', 'alex', 'daniel'
        ]
        
        selected_voice = None
        for voice in voices:
            voice_name = voice.name.lower()
            for preferred in preferred_voices:
                if preferred in voice_name:
                    selected_voice = voice
                    console.print(f"[cyan]Selected voice: {voice.name}[/cyan]")
                    break
            if selected_voice:
                break
        
        if selected_voice:
            self.tts_engine.setProperty('voice', selected_voice.id)
        elif voices:
            # Use the best available voice (usually index 1 is better than 0)
            voice_index = min(1, len(voices) - 1) if len(voices) > 1 else 0
            self.tts_engine.setProperty('voice', voices[voice_index].id)
            console.print(f"[cyan]Using voice: {voices[voice_index].name}[/cyan]")
        
        # Apply natural speech settings
        self.tts_engine.setProperty('rate', Config.VOICE_SETTINGS.get("rate", 180))
        self.tts_engine.setProperty('volume', Config.VOICE_SETTINGS.get("volume", 0.9))
        
        # Additional settings if supported
        try:
            # Some TTS engines support these properties
            if hasattr(self.tts_engine, 'setProperty'):
                self.tts_engine.setProperty('pitch', Config.VOICE_SETTINGS.get("pitch", 50))
        except:
            pass
        
    def speak(self, text):
        """Convert text to speech with natural inflection"""
        if not Config.VOICE_SETTINGS.get("enabled", True) or not text.strip():
            return
            
        console.print(f"[blue]JARVIS:[/blue] {text}")
        
        # Wait for any previous speech to complete
        while self.is_speaking:
            time.sleep(0.1)
            
        self.is_speaking = True
        
        try:
            # Process text for more natural speech
            processed_text = self.process_text_for_natural_speech(text)
            
            self.tts_engine.say(processed_text)
            self.tts_engine.runAndWait()
        except Exception as e:
            console.print(f"[red]TTS Error: {e}[/red]")
        finally:
            self.is_speaking = False
    
    def process_text_for_natural_speech(self, text):
        """Process text to make it sound more natural when spoken"""
        original = text.strip()

        # 1) Transform common metric lines into natural sentences with context
        # CPU: "CPU Usage: 5.1%" -> "Current CPU usage is 5.1 percent — load is low." 
        cpu_match = re.search(r"CPU\s*Usage:\s*([\d\.]+)%", original, re.IGNORECASE)
        if cpu_match:
            val = float(cpu_match.group(1))
            if val < 15:
                load = "low"
            elif val < 50:
                load = "moderate"
            elif val < 80:
                load = "high"
            else:
                load = "critical"
            original = f"Current CPU usage is {val:.1f} percent — load is {load}."

        # Memory: "Memory: 53.0% used (9 GB / 17 GB)"
        mem_match = re.search(r"Memory:\s*([\d\.]+)%\s*used\s*\((\d+)\s*GB\s*/\s*(\d+)\s*GB\)", original, re.IGNORECASE)
        if mem_match:
            pct = float(mem_match.group(1))
            used = int(mem_match.group(2))
            total = int(mem_match.group(3))
            original = f"Memory usage is {pct:.1f} percent — {used} of {total} gigabytes in use."

        # 2) Add slight pauses for better pacing (engine-friendly)
        processed = original.replace('. ', '. ... ')
        processed = processed.replace(', ', ', . ')
        processed = processed.replace('!', '! ... ')
        processed = processed.replace('?', '? ... ')
        
        # Emphasize certain words for JARVIS personality
        emphasis_words = {
            'sir': 'Sir.',
            'systems': 'systems.',
            'operational': 'operational.',
            'online': 'online.',
            'ready': 'ready.',
            'complete': 'complete.',
            'successful': 'successful.',
            'error': 'ERROR',
            'warning': 'warning',
            'critical': 'CRITICAL'
        }
        
        for word, replacement in emphasis_words.items():
            processed = processed.replace(word, replacement)
        
        return processed
        
    def test_voice(self):
        """Test TTS functionality"""
        test_phrases = [
            "Voice systems online.",
            "All systems nominal, Sir.",
            "How may I assist you today?"
        ]
        
        for phrase in test_phrases:
            self.speak(phrase)
            time.sleep(2)
            
    def calibrate_microphone(self):
        """Calibrate microphone for ambient noise"""
        if not self.sr_available:
            return
            
        console.print("[yellow]Calibrating microphone for ambient noise...[/yellow]")
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
            console.print("[green]✅ Microphone calibrated successfully[/green]")
        except Exception as e:
            console.print(f"[red]Microphone calibration failed: {e}[/red]")
    
    def listen_for_command(self, timeout=5, phrase_timeout=1):
        """Listen for voice commands"""
        if not self.sr_available:
            console.print("[yellow]Voice recognition not available[/yellow]")
            return None
            
        self.is_listening = True
        console.print("[cyan]🎤 Listening... (speak now)[/cyan]")
        
        try:
            with self.microphone as source:
                # Listen for audio with timeout
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_timeout)
            
            console.print("[yellow]🔄 Processing speech...[/yellow]")
            
            # Recognize speech using Google's service
            try:
                command = self.recognizer.recognize_google(audio).lower()
                console.print(f"[green]🎯 Recognized: '{command}'[/green]")
                return command
            except sr.UnknownValueError:
                console.print("[red]❌ Could not understand audio[/red]")
                return None
            except sr.RequestError as e:
                console.print(f"[red]❌ Speech recognition error: {e}[/red]")
                return None
                
        except sr.WaitTimeoutError:
            console.print("[yellow]⏰ Listening timeout - no speech detected[/yellow]")
            return None
        except Exception as e:
            console.print(f"[red]❌ Error during listening: {e}[/red]")
            return None
        finally:
            self.is_listening = False
    
    def listen_for_wake_word(self, wake_word=None):
        """Listen continuously for wake word"""
        if not self.sr_available:
            return False
            
        wake_word = wake_word or Config.WAKE_WORD
        
        try:
            with self.microphone as source:
                audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=3)
            
            try:
                command = self.recognizer.recognize_google(audio).lower()
                if wake_word in command:
                    console.print(f"[green]👋 Wake word '{wake_word}' detected![/green]")
                    return True
            except (sr.UnknownValueError, sr.RequestError):
                pass  # Ignore recognition errors for wake word detection
                
        except sr.WaitTimeoutError:
            pass  # Normal timeout, continue listening
        except Exception as e:
            console.print(f"[red]Wake word detection error: {e}[/red]")
            
        return False
    
    def list_available_voices(self):
        """List all available voices on the system"""
        voices = self.tts_engine.getProperty('voices')
        console.print("[cyan]Available voices:[/cyan]")
        for i, voice in enumerate(voices):
            current = " (CURRENT)" if voice.id == self.tts_engine.getProperty('voice') else ""
            console.print(f"[dim]  {i}: {voice.name}{current}[/dim]")
            console.print(f"[dim]     ID: {voice.id}[/dim]")
            console.print(f"[dim]     Languages: {getattr(voice, 'languages', 'Unknown')}[/dim]")
        return voices
    
    def change_voice(self, voice_index_or_name):
        """Change the TTS voice"""
        voices = self.tts_engine.getProperty('voices')
        
        if isinstance(voice_index_or_name, int):
            if 0 <= voice_index_or_name < len(voices):
                selected_voice = voices[voice_index_or_name]
                self.tts_engine.setProperty('voice', selected_voice.id)
                console.print(f"[green]Voice changed to: {selected_voice.name}[/green]")
                return True
        else:
            # Search by name
            for voice in voices:
                if voice_index_or_name.lower() in voice.name.lower():
                    self.tts_engine.setProperty('voice', voice.id)
                    console.print(f"[green]Voice changed to: {voice.name}[/green]")
                    return True
        
        console.print(f"[red]Voice '{voice_index_or_name}' not found[/red]")
        return False
    
    def test_current_voice(self):
        """Test the current voice with a sample phrase"""
        test_phrase = "Good afternoon, Sir. All systems are operational and ready for your commands."
        self.speak(test_phrase)

    # -------------------- Microphone utilities --------------------
    def list_input_devices(self):
        """Return a list of available microphone device names."""
        try:
            return sr.Microphone.list_microphone_names()
        except Exception as e:
            console.print(f"[red]Could not list microphones: {e}[/red]")
            return []

    def get_current_microphone_info(self):
        """Return a dict with current mic index and name (best-effort)."""
        info = {"index": self.mic_index, "name": None}
        try:
            names = self.list_input_devices()
            if self.mic_index is not None and 0 <= self.mic_index < len(names):
                info["name"] = names[self.mic_index]
            else:
                # Determine default device name via PyAudio
                pa = sr.Microphone.get_pyaudio()
                try:
                    dev = pa.get_default_input_device_info()
                    info["index"] = dev.get('index', None)
                    idx = info["index"]
                    if idx is not None and 0 <= idx < len(names):
                        info["name"] = names[idx]
                    else:
                        info["name"] = dev.get('name', 'Default Input Device')
                finally:
                    try:
                        pa.terminate()
                    except Exception:
                        pass
        except Exception:
            pass
        return info

    def set_microphone(self, index_or_name):
        """Select a specific microphone by index or partial name (case-insensitive)."""
        try:
            names = self.list_input_devices()
            target_index = None
            # Try integer index
            if isinstance(index_or_name, int):
                target_index = index_or_name
            else:
                s = str(index_or_name).strip()
                if s.isdigit():
                    target_index = int(s)
                else:
                    # Partial name match
                    lower = s.lower()
                    for i, n in enumerate(names):
                        if lower in n.lower():
                            target_index = i
                            break
            if target_index is None or target_index < 0 or target_index >= len(names):
                return False, f"Microphone not found: {index_or_name}"

            # Recreate microphone with the chosen device
            self.microphone = sr.Microphone(device_index=target_index)
            self.mic_index = target_index
            # Recalibrate for the new device
            self.calibrate_microphone()
            console.print(f"[green]Microphone set to: {names[target_index]} (index {target_index})[/green]")
            return True, f"Using microphone: {names[target_index]}"
        except Exception as e:
            return False, f"Failed to set microphone: {e}"
