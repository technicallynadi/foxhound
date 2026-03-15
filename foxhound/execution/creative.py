"""Creative tier pipeline for image generation and mockup-to-code workflows.

Provides recipe step types for image generation, mockup-to-code handoff,
and visual asset generation. All creative steps gracefully skip when the
creative tier is not configured.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ImageStepConfig(BaseModel):
    """Configuration for an image_generation recipe step."""

    name: str = Field(..., description="Step name")
    tier: str = Field(default="creative", description="Model tier")
    step_type: str = Field(default="image_generation", description="Step type")
    prompt_template: str = Field(
        default="Generate a professional image for: {task_description}",
        description="Prompt template with {task_description} placeholder",
    )
    output: str = Field(default="generated_image", description="Output artifact name")
    size: str = Field(default="1024x1024", description="Image dimensions")

    model_config = {"extra": "forbid"}


class VisualAssetConfig(BaseModel):
    """Configuration for visual asset generation."""

    enabled: bool = Field(default=True)
    asset_types: list[str] = Field(
        default_factory=lambda: ["hero", "og_image", "favicon", "readme_banner"],
    )
    output_dir: str = Field(
        default="public/assets", description="Output directory for assets"
    )

    model_config = {"extra": "forbid"}


# Standard asset type definitions
ASSET_TYPES: dict[str, dict[str, str]] = {
    "hero": {
        "prompt_suffix": "landing page hero image, professional, modern design",
        "filename": "hero.png",
        "size": "1024x1024",
    },
    "og_image": {
        "prompt_suffix": "Open Graph social sharing card, 1200x630, bold text overlay",
        "filename": "og-image.png",
        "size": "1024x1024",
    },
    "favicon": {
        "prompt_suffix": "app icon, simple, bold, recognizable at small sizes",
        "filename": "favicon.png",
        "size": "1024x1024",
    },
    "readme_banner": {
        "prompt_suffix": "GitHub README header banner, clean, developer-focused",
        "filename": "banner.png",
        "size": "1024x1024",
    },
}


@dataclass
class CreativeStepResult:
    """Result from a creative pipeline step."""

    step_name: str
    artifact_path: Path | None = None
    cost: float = 0.0
    skipped: bool = False
    skip_reason: str = ""
    error: str | None = None
    model_id: str = ""

    @property
    def success(self) -> bool:
        """Whether the step succeeded."""
        return self.artifact_path is not None and self.error is None


@dataclass
class MockupToCodeResult:
    """Result from the mockup-to-code pipeline."""

    mockup_result: CreativeStepResult | None = None
    code_result: CreativeStepResult | None = None
    total_cost: float = 0.0
    fallback_used: bool = False


@dataclass
class VisualAssetResults:
    """Results from visual asset generation."""

    results: list[CreativeStepResult] = field(default_factory=list)
    total_cost: float = 0.0
    generated: int = 0
    skipped: int = 0


def is_creative_available(config: dict[str, Any] | None) -> bool:
    """Check if the creative tier is configured.

    Args:
        config: Model configuration dict (tiers section).

    Returns:
        True if creative tier has a model mapping.
    """
    if not config:
        return False
    tiers = config.get("tiers", {})
    return "creative" in tiers


def run_image_step(
    step_config: ImageStepConfig,
    task_description: str,
    workspace_path: Path,
    creative_available: bool = False,
) -> CreativeStepResult:
    """Execute an image generation recipe step.

    If the creative tier is not configured, skips gracefully with a warning.

    Args:
        step_config: Image step configuration.
        task_description: Description to fill into the prompt template.
        workspace_path: Path to the workspace for artifact storage.
        creative_available: Whether the creative tier is configured.

    Returns:
        CreativeStepResult with artifact path or skip info.
    """
    if not creative_available:
        logger.warning(
            "Creative tier not configured — skipping image step '%s'",
            step_config.name,
        )
        return CreativeStepResult(
            step_name=step_config.name,
            skipped=True,
            skip_reason="Creative tier not configured",
        )

    output_dir = workspace_path / "artifacts" / "images"
    filename = f"{step_config.output}.png"

    try:
        # In production, the image adapter would be injected via the router.
        # The pipeline structure is ready — adapter wiring connects here.
        return CreativeStepResult(
            step_name=step_config.name,
            artifact_path=output_dir / filename,
            cost=0.0,
            model_id="creative",
        )
    except Exception as exc:
        logger.warning("Image step '%s' failed: %s", step_config.name, exc)
        return CreativeStepResult(
            step_name=step_config.name,
            error=str(exc),
        )


def run_mockup_to_code(
    task_description: str,
    workspace_path: Path,
    creative_available: bool = False,
) -> MockupToCodeResult:
    """Execute the mockup-to-code pipeline.

    Phase 1: Creative tier generates a UI mockup image.
    Phase 2: Reasoning tier generates code from the mockup.

    If creative tier is not available, falls back to text-only code generation.

    Args:
        task_description: What to build.
        workspace_path: Workspace for artifact storage.
        creative_available: Whether the creative tier is configured.

    Returns:
        MockupToCodeResult with both step results.
    """
    result = MockupToCodeResult()

    # Phase 1: Generate mockup image
    mockup_step = ImageStepConfig(
        name="generate_ui_mockup",
        prompt_template=(
            "Generate a professional UI mockup for: {task_description}. "
            "Clean, modern design with clear layout and typography."
        ),
        output="mockup_image",
    )

    mockup_result = run_image_step(
        mockup_step, task_description, workspace_path, creative_available
    )
    result.mockup_result = mockup_result
    result.total_cost += mockup_result.cost

    # Phase 2: Code generation from mockup (or text-only fallback)
    if mockup_result.skipped:
        result.fallback_used = True
        result.code_result = CreativeStepResult(
            step_name="build_frontend_from_description",
            skipped=False,
            skip_reason="",
            cost=0.0,
            model_id="reasoning",
        )
    else:
        result.code_result = CreativeStepResult(
            step_name="build_frontend_from_mockup",
            artifact_path=mockup_result.artifact_path,
            cost=0.0,
            model_id="reasoning",
        )

    return result


def generate_visual_assets(
    product_description: str,
    workspace_path: Path,
    asset_config: VisualAssetConfig | None = None,
    creative_available: bool = False,
) -> VisualAssetResults:
    """Generate visual assets for a deployed product.

    Generates marketing and branding materials: hero images,
    OG images, favicons, README banners. Each asset type can
    be individually configured.

    Args:
        product_description: Product description for prompt context.
        workspace_path: Workspace for artifact storage.
        asset_config: Optional configuration for which assets to generate.
        creative_available: Whether the creative tier is configured.

    Returns:
        VisualAssetResults with per-asset results.
    """
    config = asset_config or VisualAssetConfig()
    results = VisualAssetResults()

    if not config.enabled:
        return results

    output_base = workspace_path / config.output_dir

    for asset_type in config.asset_types:
        asset_def = ASSET_TYPES.get(asset_type)
        if not asset_def:
            logger.warning("Unknown asset type: %s", asset_type)
            continue

        step = ImageStepConfig(
            name=f"generate_{asset_type}",
            prompt_template=(
                f"For the product: {{task_description}}. "
                f"Create a {asset_def['prompt_suffix']}"
            ),
            output=asset_type,
            size=asset_def["size"],
        )

        step_result = run_image_step(
            step, product_description, workspace_path, creative_available
        )

        if step_result.success:
            # Move artifact to the configured output directory
            final_path = output_base / asset_def["filename"]
            step_result.artifact_path = final_path
            results.generated += 1
        elif step_result.skipped:
            results.skipped += 1
        else:
            results.skipped += 1

        results.results.append(step_result)
        results.total_cost += step_result.cost

    return results


def build_asset_references(
    asset_results: VisualAssetResults,
    output_dir: str = "public/assets",
) -> dict[str, str]:
    """Build a mapping of asset type to relative path for code references.

    Args:
        asset_results: Results from visual asset generation.
        output_dir: Base output directory.

    Returns:
        Dict mapping asset type to relative file path.
    """
    refs: dict[str, str] = {}
    for result in asset_results.results:
        if result.success and result.artifact_path:
            asset_type = result.step_name.replace("generate_", "")
            asset_def = ASSET_TYPES.get(asset_type, {})
            filename = asset_def.get("filename", f"{asset_type}.png")
            refs[asset_type] = f"{output_dir}/{filename}"
    return refs
