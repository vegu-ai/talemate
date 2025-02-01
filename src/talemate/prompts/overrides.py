import os
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional

from talemate.prompts.base import prepended_template_dirs

@dataclass
class TemplateOverride:
    template_name: str
    override_path: str
    default_path: str
    age_difference: str  # Human readable time difference
    override_newer: bool

def get_template_overrides(agent_type: str) -> List[TemplateOverride]:
    """
    Identifies template files that are being overridden and calculates age differences
    between override and default templates.
    
    Args:
        agent_type (str): The type of agent to check templates for
        
    Returns:
        List[TemplateOverride]: List of template overrides with their details
    """
    # Get the directory of the current file (assuming this is in the same dir as base_prompt.py)
    dir_path = os.path.dirname(os.path.realpath(__file__))
    
    # Define template directories as in the Prompt class
    default_template_dirs = [
        os.path.join(dir_path, "..", "..", "..", "templates", "prompts", agent_type),
        os.path.join(dir_path, "templates", agent_type),
    ]
    
    template_dirs = prepended_template_dirs.get() + default_template_dirs
    overrides = []
    
    # Helper function to get file modification time
    def get_file_mtime(filepath: str) -> Optional[datetime]:
        try:
            return datetime.fromtimestamp(os.path.getmtime(filepath))
        except (OSError, ValueError):
            return None
            
    # Helper function to calculate human readable time difference
    def get_time_difference(time1: datetime, time2: datetime) -> str:
        diff = abs(time1 - time2)
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        
        parts = []
        if days > 0:
            parts.append(f"{days} days")
        elif hours > 0:
            parts.append(f"{hours} hours")
        elif minutes > 0:
            parts.append(f"{minutes} minutes")
            
        return ", ".join(parts) if parts else "less than a minute"

    # Build a map of template names to their locations
    template_locations = {}
    
    for template_dir in template_dirs:
        if not os.path.exists(template_dir):
            continue
            
        for root, _, files in os.walk(template_dir):
            for filename in files:
                if not filename.endswith('.jinja2'):
                    continue
                    
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(root, template_dir)
                template_name = os.path.join(rel_path, filename)
                
                if template_name not in template_locations:
                    template_locations[template_name] = []
                template_locations[template_name].append(filepath)
    
    # Analyze overrides
    for template_name, locations in template_locations.items():
        if len(locations) < 2:
            continue
            
        # The first location is the override, the last is the default
        override_path = locations[0]
        default_path = locations[-1]
        
        override_time = get_file_mtime(override_path)
        default_time = get_file_mtime(default_path)
        
        if not override_time or not default_time:
            continue
            
        age_diff = get_time_difference(default_time, override_time)
        override_newer = override_time > default_time
        
        overrides.append(TemplateOverride(
            template_name=template_name,
            override_path=override_path,
            default_path=default_path,
            age_difference=age_diff,
            override_newer=override_newer
        ))
    
    return overrides