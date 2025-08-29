import os
import shutil
from pathlib import Path
from datetime import datetime

class FileManagerSkill:
    def __init__(self):
        # Use the directory where the jarvis script is located, not the current working directory
        script_dir = Path(__file__).parent.parent.absolute()
        self.current_directory = str(script_dir)
    
    def file_exists(self, filename: str) -> bool:
        """Check whether a file exists in the current directory.
        Accepts names with or without extension and cleans invalid characters.
        Returns True if found, otherwise False.
        """
        try:
            if not filename:
                return False
            name = self._clean_filename(filename)
            # Try exact
            path = Path(self.current_directory) / name
            if path.exists() and path.is_file():
                return True
            # Try with .txt fallback when no extension was provided originally
            if not Path(name).suffix:
                path_txt = Path(self.current_directory) / f"{name}.txt"
                if path_txt.exists() and path_txt.is_file():
                    return True
            return False
        except Exception:
            return False
        
    def create_file(self, filename, content=""):
        """Create a new file with optional content"""
        try:
            # Clean the filename
            filename = self._clean_filename(filename)
            
            # Add .txt extension if no extension provided
            if not Path(filename).suffix:
                filename += ".txt"
            
            filepath = Path(self.current_directory) / filename
            
            # Check if file already exists
            if filepath.exists():
                return f"File '{filename}' already exists. Would you like me to overwrite it?"
            
            # Create the file
            with open(filepath, 'w', encoding='utf-8') as f:
                if content:
                    f.write(content)
                    content_length = len(content)
                else:
                    default_content = f"# {filename}\n\nCreated by JARVIS on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f.write(default_content)
                    content_length = len(default_content)
            
            return f"File '{filename}' created successfully at {filepath}\nContent: {content_length} characters written"
            
        except Exception as e:
            return f"Error creating file: {e}"
    
    def create_file_at_location(self, filename, content="", location=""):
        """Create a file at a specific location"""
        try:
            # Clean the filename
            filename = self._clean_filename(filename)
            
            # Add .txt extension if no extension provided
            if not Path(filename).suffix:
                filename += ".txt"
            
            # Determine target directory
            if location and "desktop" in location.lower():
                # Use desktop directory
                import os
                desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
                target_dir = Path(desktop_path)
            else:
                # Use current JARVIS directory
                target_dir = Path(self.current_directory)
            
            # Ensure target directory exists
            target_dir.mkdir(parents=True, exist_ok=True)
            
            filepath = target_dir / filename
            
            # Check if file already exists
            if filepath.exists():
                return f"File '{filename}' already exists at {target_dir}. Would you like me to overwrite it?"
            
            # Create the file
            with open(filepath, 'w', encoding='utf-8') as f:
                if content:
                    f.write(content)
                    content_length = len(content)
                else:
                    default_content = f"# {filename}\n\nCreated by JARVIS on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f.write(default_content)
                    content_length = len(default_content)
            
            return f"File '{filename}' created successfully at {filepath}\nContent: {content_length} characters written"
            
        except Exception as e:
            return f"Error creating file: {e}"
    
    def read_file(self, filename):
        """Read contents of a file"""
        try:
            filename = self._clean_filename(filename)
            filepath = Path(self.current_directory) / filename
            
            if not filepath.exists():
                # Try with .txt extension
                filepath = Path(self.current_directory) / (filename + ".txt")
                if not filepath.exists():
                    return f"File '{filename}' not found in {self.current_directory}"
            
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if len(content) > 500:
                content = content[:500] + "... (truncated)"
            
            return f"Contents of '{filepath.name}':\n\n{content}"
            
        except Exception as e:
            return f"Error reading file: {e}"
    
    def delete_file(self, filename):
        """Delete a file"""
        try:
            filename = self._clean_filename(filename)
            filepath = Path(self.current_directory) / filename
            
            if not filepath.exists():
                # Try with .txt extension
                filepath = Path(self.current_directory) / (filename + ".txt")
                if not filepath.exists():
                    return f"File '{filename}' not found"
            
            filepath.unlink()
            return f"File '{filepath.name}' deleted successfully"
            
        except Exception as e:
            return f"Error deleting file: {e}"
    
    def list_files(self, directory=None):
        """List files in current or specified directory"""
        try:
            if directory:
                target_dir = Path(directory)
            else:
                target_dir = Path(self.current_directory)
            
            if not target_dir.exists() or not target_dir.is_dir():
                return f"Directory '{target_dir}' does not exist"
            
            files = []
            folders = []
            
            for item in target_dir.iterdir():
                if item.is_file():
                    size = item.stat().st_size
                    if size < 1024:
                        size_str = f"{size} B"
                    elif size < 1024*1024:
                        size_str = f"{size/1024:.1f} KB"
                    else:
                        size_str = f"{size/(1024*1024):.1f} MB"
                    
                    files.append(f"📄 {item.name} ({size_str})")
                elif item.is_dir():
                    folders.append(f"📁 {item.name}/")
            
            result = f"Contents of {target_dir}:\n\n"
            
            if folders:
                result += "Folders:\n"
                for folder in sorted(folders)[:10]:  # Limit to 10 items
                    result += f"  {folder}\n"
                if len(folders) > 10:
                    result += f"  ... and {len(folders) - 10} more folders\n"
                result += "\n"
            
            if files:
                result += "Files:\n"
                for file in sorted(files)[:10]:  # Limit to 10 items
                    result += f"  {file}\n"
                if len(files) > 10:
                    result += f"  ... and {len(files) - 10} more files\n"
            
            if not files and not folders:
                result += "Directory is empty"
            
            return result
            
        except Exception as e:
            return f"Error listing files: {e}"
    
    def create_folder(self, foldername):
        """Create a new folder"""
        try:
            foldername = self._clean_filename(foldername)
            folderpath = Path(self.current_directory) / foldername
            
            if folderpath.exists():
                return f"Folder '{foldername}' already exists"
            
            folderpath.mkdir(parents=True)
            return f"Folder '{foldername}' created successfully"
            
        except Exception as e:
            return f"Error creating folder: {e}"
    
    def copy_file(self, source, destination):
        """Copy a file"""
        try:
            source = self._clean_filename(source)
            destination = self._clean_filename(destination)
            
            source_path = Path(self.current_directory) / source
            dest_path = Path(self.current_directory) / destination
            
            if not source_path.exists():
                return f"Source file '{source}' not found"
            
            shutil.copy2(source_path, dest_path)
            return f"File copied from '{source}' to '{destination}'"
            
        except Exception as e:
            return f"Error copying file: {e}"
    
    def rename_file(self, old_name, new_name):
        """Rename a file"""
        try:
            old_name = self._clean_filename(old_name)
            new_name = self._clean_filename(new_name)
            
            old_path = Path(self.current_directory) / old_name
            new_path = Path(self.current_directory) / new_name
            
            if not old_path.exists():
                return f"File '{old_name}' not found"
            
            if new_path.exists():
                return f"File '{new_name}' already exists"
            
            old_path.rename(new_path)
            return f"File renamed from '{old_name}' to '{new_name}'"
            
        except Exception as e:
            return f"Error renaming file: {e}"
    
    def get_file_info(self, filename):
        """Get information about a file"""
        try:
            filename = self._clean_filename(filename)
            filepath = Path(self.current_directory) / filename
            
            if not filepath.exists():
                # Try with .txt extension
                filepath = Path(self.current_directory) / (filename + ".txt")
                if not filepath.exists():
                    return f"File '{filename}' not found"
            
            stat = filepath.stat()
            size = stat.st_size
            
            if size < 1024:
                size_str = f"{size} bytes"
            elif size < 1024*1024:
                size_str = f"{size/1024:.1f} KB"
            else:
                size_str = f"{size/(1024*1024):.1f} MB"
            
            created = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
            modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            
            return f"File information for '{filepath.name}':\nSize: {size_str}\nCreated: {created}\nModified: {modified}\nPath: {filepath}"
            
        except Exception as e:
            return f"Error getting file info: {e}"
    
    def change_directory(self, directory):
        """Change current working directory"""
        try:
            new_dir = Path(directory).resolve()
            
            if not new_dir.exists():
                return f"Directory '{directory}' does not exist"
            
            if not new_dir.is_dir():
                return f"'{directory}' is not a directory"
            
            self.current_directory = str(new_dir)
            os.chdir(self.current_directory)
            
            return f"Changed directory to {self.current_directory}"
            
        except Exception as e:
            return f"Error changing directory: {e}"
    
    def get_current_directory(self):
        """Get current working directory"""
        return f"Current directory: {self.current_directory}"
    
    def _clean_filename(self, filename):
        """Clean filename to remove invalid characters"""
        # Remove quotes and extra spaces
        filename = filename.strip(' "\'')
        
        # Replace invalid characters with underscores
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Replace spaces with underscores
        filename = filename.replace(' ', '_')
        
        return filename
