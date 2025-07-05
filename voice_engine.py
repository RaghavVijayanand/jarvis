import pyttsx3
import speech_recognition as sr
import threading
import time
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
            self.microphone = sr.Microphone()
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
        self.tts_engine.setProperty('rate', Config.VOICE_SETTINGS["rate"])
        self.tts_engine.setProperty('volume', Config.VOICE_SETTINGS["volume"])
        
        # Additional settings if supported
        try:
            # Some TTS engines support these properties
            if hasattr(self.tts_engine, 'setProperty'):
                self.tts_engine.setProperty('pitch', Config.VOICE_SETTINGS.get("pitch", 50))
        except:
            pass
        
    def speak(self, text):
        """Convert text to speech with natural inflection"""
        if not text.strip():
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
        # Add slight pauses for better pacing
        processed = text.replace('. ', '. ... ')  # Pause after sentences
        processed = processed.replace(', ', ', . ')  # Slight pause after commas
        processed = processed.replace('!', '! ... ')  # Pause after exclamations
        processed = processed.replace('?', '? ... ')  # Pause after questions
        
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
