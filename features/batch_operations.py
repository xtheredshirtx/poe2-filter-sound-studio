"""
Batch Operations Module - Template management and bulk editing
"""

import json
import os
from typing import List, Optional, Callable
from core.data_models import FilterBlock, ColorTemplate
from features.color_editor import ColorManager


class TemplateManager:
    """Manages color templates - load, save, apply."""

    def __init__(self, templates_path: str = None):
        """
        Initialize template manager.

        Args:
            templates_path: Path to templates.json file
        """
        if templates_path is None:
            # Default path
            script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            templates_path = os.path.join(script_dir, "data", "color_templates", "templates.json")

        self.templates_path = templates_path
        self.templates: List[ColorTemplate] = []
        self.load_templates()

    def load_templates(self):
        """Load templates from JSON file."""
        if not os.path.exists(self.templates_path):
            # Create default templates if file doesn't exist
            self.templates = self._get_default_templates()
            self.save_templates()
        else:
            try:
                with open(self.templates_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                self.templates = []
                for t in data.get("templates", []):
                    template = ColorTemplate(
                        name=t["name"],
                        description=t["description"],
                        text_color=tuple(t["text_color"]),
                        border_color=tuple(t["border_color"]),
                        bg_color=tuple(t["bg_color"]),
                        tags=t.get("tags", [])
                    )
                    self.templates.append(template)

            except Exception as e:
                print(f"Error loading templates: {e}")
                self.templates = self._get_default_templates()

    def save_templates(self):
        """Save templates to JSON file."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.templates_path), exist_ok=True)

            data = {
                "templates": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "text_color": list(t.text_color),
                        "border_color": list(t.border_color),
                        "bg_color": list(t.bg_color),
                        "tags": t.tags
                    }
                    for t in self.templates
                ]
            }

            with open(self.templates_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            print(f"Error saving templates: {e}")

    def _get_default_templates(self) -> List[ColorTemplate]:
        """Return default color templates."""
        return [
            ColorTemplate(
                name="Unique - Gold",
                description="Classic gold theme for unique items",
                text_color=(175, 96, 37, 255),
                border_color=(175, 96, 37, 255),
                bg_color=(50, 27, 10, 200),
                tags=["unique", "rare", "valuable"]
            ),
            ColorTemplate(
                name="Currency - Green",
                description="Bright green for currency items",
                text_color=(170, 158, 130, 255),
                border_color=(255, 255, 255, 255),
                bg_color=(0, 0, 0, 200),
                tags=["currency", "important"]
            ),
            ColorTemplate(
                name="Rare - Yellow",
                description="Standard yellow theme for rare items",
                text_color=(255, 255, 119, 255),
                border_color=(255, 255, 119, 255),
                bg_color=(50, 50, 20, 180),
                tags=["rare", "crafting"]
            ),
            ColorTemplate(
                name="Maps - Purple",
                description="Purple theme for maps",
                text_color=(130, 90, 160, 255),
                border_color=(130, 90, 160, 255),
                bg_color=(25, 15, 35, 200),
                tags=["maps", "endgame"]
            ),
        ]

    def get_template(self, name: str) -> Optional[ColorTemplate]:
        """Get a template by name."""
        for t in self.templates:
            if t.name == name:
                return t
        return None

    def get_all_templates(self) -> List[ColorTemplate]:
        """Get all templates."""
        return self.templates.copy()

    def add_template(self, template: ColorTemplate):
        """Add a new template."""
        # Check if template with same name exists
        for i, t in enumerate(self.templates):
            if t.name == template.name:
                # Replace existing
                self.templates[i] = template
                self.save_templates()
                return

        # Add new
        self.templates.append(template)
        self.save_templates()

    def delete_template(self, name: str) -> bool:
        """Delete a template by name."""
        for i, t in enumerate(self.templates):
            if t.name == name:
                del self.templates[i]
                self.save_templates()
                return True
        return False

    def apply_template_to_block(self, template: ColorTemplate, block: FilterBlock, lines: List[str]) -> List[str]:
        """
        Apply a template to a filter block.

        Args:
            template: ColorTemplate to apply
            block: FilterBlock to modify
            lines: Filter file lines

        Returns:
            Modified lines list
        """
        return ColorManager.apply_all_colors(
            lines, block,
            text_rgba=template.text_color,
            border_rgba=template.border_color,
            bg_rgba=template.bg_color
        )

    def apply_template_to_blocks(self, template: ColorTemplate, blocks: List[FilterBlock],
                                lines: List[str], progress_callback: Optional[Callable[[int, int], None]] = None) -> List[str]:
        """
        Apply a template to multiple blocks.

        Args:
            template: ColorTemplate to apply
            blocks: List of FilterBlocks to modify
            lines: Filter file lines
            progress_callback: Optional callback(current, total) for progress updates

        Returns:
            Modified lines list
        """
        total = len(blocks)
        for i, block in enumerate(blocks):
            self.apply_template_to_block(template, block, lines)

            if progress_callback:
                progress_callback(i + 1, total)

        return lines


class BulkSoundAssigner:
    """Assign sounds to multiple blocks matching criteria."""

    @staticmethod
    def assign_sound_to_blocks(blocks: List[FilterBlock], lines: List[str], sound_line: str,
                              progress_callback: Optional[Callable[[int, int], None]] = None) -> List[str]:
        """
        Assign a sound to multiple blocks.

        Args:
            blocks: List of FilterBlocks to modify
            lines: Filter file lines
            sound_line: Sound line to add (e.g., 'CustomAlertSound "sound.wav" 250')
            progress_callback: Optional callback(current, total) for progress updates

        Returns:
            Modified lines list
        """
        import re

        total = len(blocks)
        for i, block in enumerate(blocks):
            # Detect indentation
            indent = ColorManager.detect_indent(lines, block.start_idx, block.end_idx)

            # Format sound line with proper indentation
            formatted_sound = f"{indent}{sound_line.strip()}\n"

            # Find existing sound lines
            sound_line_indices = []
            for j in range(block.start_idx + 1, block.end_idx):
                if re.match(r'^\s*(CustomAlertSound|PlayAlertSound)\s+', lines[j], re.IGNORECASE):
                    sound_line_indices.append(j)

            if sound_line_indices:
                # Replace first sound line
                lines[sound_line_indices[0]] = formatted_sound

                # Remove other sound lines (working backwards to preserve indices)
                for idx in reversed(sound_line_indices[1:]):
                    del lines[idx]
                    block.end_idx -= 1
            else:
                # Insert sound line before the end of the block
                lines.insert(block.end_idx, formatted_sound)
                block.end_idx += 1

            if progress_callback:
                progress_callback(i + 1, total)

        return lines

    @staticmethod
    def remove_sounds_from_blocks(blocks: List[FilterBlock], lines: List[str],
                                 progress_callback: Optional[Callable[[int, int], None]] = None) -> List[str]:
        """
        Remove sounds from multiple blocks.

        Args:
            blocks: List of FilterBlocks to modify
            lines: Filter file lines
            progress_callback: Optional callback(current, total) for progress updates

        Returns:
            Modified lines list
        """
        import re

        total = len(blocks)
        for i, block in enumerate(blocks):
            # Find and remove sound lines (working backwards to preserve indices)
            for j in range(block.end_idx - 1, block.start_idx, -1):
                if re.match(r'^\s*(CustomAlertSound|PlayAlertSound)\s+', lines[j], re.IGNORECASE):
                    del lines[j]
                    block.end_idx -= 1

            if progress_callback:
                progress_callback(i + 1, total)

        return lines

    @staticmethod
    def change_volume_in_blocks(blocks: List[FilterBlock], lines: List[str], new_volume: int,
                               progress_callback: Optional[Callable[[int, int], None]] = None) -> List[str]:
        """
        Change volume for sounds in multiple blocks.

        Args:
            blocks: List of FilterBlocks to modify
            lines: Filter file lines
            new_volume: New volume value (0-300)
            progress_callback: Optional callback(current, total) for progress updates

        Returns:
            Modified lines list
        """
        import re

        total = len(blocks)
        for i, block in enumerate(blocks):
            # Find sound lines and update volume
            for j in range(block.start_idx + 1, block.end_idx):
                # Match CustomAlertSound or PlayAlertSound
                match_custom = re.match(r'^(\s*)(CustomAlertSound\s+"[^"]+"\s+)(\d+)', lines[j], re.IGNORECASE)
                match_play = re.match(r'^(\s*)(PlayAlertSound\s+\d+\s+)(\d+)', lines[j], re.IGNORECASE)

                if match_custom:
                    lines[j] = f"{match_custom.group(1)}{match_custom.group(2)}{new_volume}\n"
                elif match_play:
                    lines[j] = f"{match_play.group(1)}{match_play.group(2)}{new_volume}\n"

            if progress_callback:
                progress_callback(i + 1, total)

        return lines
