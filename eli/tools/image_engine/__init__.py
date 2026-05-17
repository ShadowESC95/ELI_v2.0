"""GUI bridge and nested runtime exports for the local image engine."""

from .gui_bridge import (
    ImageGenerationRequest,
    ImageGenerationResult,
    PALETTE_CHOICES,
    SCENE_CHOICES,
    STYLE_CHOICES,
    build_personalized_prompt,
    discover_local_image_models,
    discover_presets,
    generate_images,
    list_recent_outputs,
    output_dir,
    tool_root,
)

__all__ = [
    "ImageGenerationRequest",
    "ImageGenerationResult",
    "SCENE_CHOICES",
    "STYLE_CHOICES",
    "PALETTE_CHOICES",
    "tool_root",
    "output_dir",
    "discover_local_image_models",
    "discover_presets",
    "list_recent_outputs",
    "build_personalized_prompt",
    "generate_images",
]
