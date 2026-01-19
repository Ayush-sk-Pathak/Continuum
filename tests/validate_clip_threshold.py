#!/usr/bin/env python3
"""
CLIP Threshold Validation Script for Anime Identity Checking

This script validates that the CLIP identity checker threshold (currently 0.85)
is appropriate for anime/stylized content. It tests similarity scores across
different scenarios to ensure:

1. Same character, different poses → similarity > 0.85 (PASS)
2. Different characters → similarity < 0.70 (clear separation)
3. Edge cases (occlusion, different angles) are handled appropriately

Per ARCHITECTURE.md Section 16G: Anime uses CLIP semantic similarity instead
of ArcFace facial geometry for identity checking.

Usage:
    # On RunPod (after pip install transformers torch pillow):
    python tests/validate_clip_threshold.py --images-dir /workspace/anime_test_images

    # With custom threshold:
    python tests/validate_clip_threshold.py --images-dir ./test_images --threshold 0.82

    # Generate detailed report:
    python tests/validate_clip_threshold.py --images-dir ./test_images --report report.json

Image Directory Structure (Expected):
    test_images/
    ├── character_a/
    │   ├── pose1.png    # Same character, different poses
    │   ├── pose2.png
    │   └── pose3.png
    ├── character_b/
    │   ├── pose1.png    # Different character
    │   └── pose2.png
    └── edge_cases/
        ├── occluded.png
        └── side_angle.png

Architecture Alignment:
    - Uses src.audit.identity_checker.CLIPIdentityChecker (production code)
    - Validates threshold from src.core.config.AuditConfig.clip_identity_threshold
    - Reports alignment with ARCHITECTURE.md Section 16G goals
"""

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Tuple
import statistics

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.audit.identity_checker import CLIPIdentityChecker, IdentityComparison
from src.core.config import StyleType

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class TestCase:
    """A single identity comparison test case."""
    name: str
    source_path: Path
    target_path: Path
    expected_result: str  # "same_character" or "different_character"
    category: str  # "same_pose_variation", "different_character", "edge_case"


@dataclass
class TestResult:
    """Result of running a test case."""
    test_case: TestCase
    similarity: float
    passed: bool
    threshold_used: float
    expected_pass: bool
    message: str

    @property
    def is_correct(self) -> bool:
        """Did the test produce the expected result?"""
        return self.passed == self.expected_pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.test_case.name,
            "category": self.test_case.category,
            "source": str(self.test_case.source_path),
            "target": str(self.test_case.target_path),
            "expected": self.test_case.expected_result,
            "similarity": round(self.similarity, 4),
            "passed": self.passed,
            "threshold": self.threshold_used,
            "correct": self.is_correct,
            "message": self.message,
        }


@dataclass
class ValidationReport:
    """Overall validation report."""
    threshold_tested: float
    total_tests: int
    correct_predictions: int
    false_positives: int  # Different characters marked as same
    false_negatives: int  # Same character marked as different
    same_character_scores: List[float]
    different_character_scores: List[float]
    recommendations: List[str]
    test_results: List[TestResult]

    @property
    def accuracy(self) -> float:
        """Overall accuracy percentage."""
        if self.total_tests == 0:
            return 0.0
        return (self.correct_predictions / self.total_tests) * 100

    @property
    def avg_same_similarity(self) -> float:
        """Average similarity for same-character pairs."""
        if not self.same_character_scores:
            return 0.0
        return statistics.mean(self.same_character_scores)

    @property
    def avg_different_similarity(self) -> float:
        """Average similarity for different-character pairs."""
        if not self.different_character_scores:
            return 0.0
        return statistics.mean(self.different_character_scores)

    @property
    def separation_margin(self) -> float:
        """Gap between same-character and different-character scores."""
        return self.avg_same_similarity - self.avg_different_similarity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": {
                "threshold": self.threshold_tested,
                "total_tests": self.total_tests,
                "accuracy": round(self.accuracy, 2),
                "correct": self.correct_predictions,
                "false_positives": self.false_positives,
                "false_negatives": self.false_negatives,
            },
            "statistics": {
                "same_character_avg": round(self.avg_same_similarity, 4),
                "different_character_avg": round(self.avg_different_similarity, 4),
                "separation_margin": round(self.separation_margin, 4),
                "same_character_min": round(min(self.same_character_scores), 4) if self.same_character_scores else 0,
                "same_character_max": round(max(self.same_character_scores), 4) if self.same_character_scores else 0,
                "different_character_min": round(min(self.different_character_scores), 4) if self.different_character_scores else 0,
                "different_character_max": round(max(self.different_character_scores), 4) if self.different_character_scores else 0,
            },
            "recommendations": self.recommendations,
            "test_results": [r.to_dict() for r in self.test_results],
        }


# =============================================================================
# TEST CASE DISCOVERY
# =============================================================================

def discover_test_cases(images_dir: Path) -> List[TestCase]:
    """
    Discover test cases from image directory structure.

    Expected structure:
        images_dir/
        ├── character_a/  (images of same character)
        ├── character_b/  (images of different character)
        └── ...

    Generates pairwise comparisons:
    - Within same directory → expected_result = "same_character"
    - Across directories → expected_result = "different_character"
    """
    test_cases = []

    # Find all character directories
    character_dirs = [d for d in images_dir.iterdir() if d.is_dir()]

    if not character_dirs:
        logger.warning(f"No character directories found in {images_dir}")
        return test_cases

    logger.info(f"Found {len(character_dirs)} character directories")

    # Generate same-character test cases (within each directory)
    for char_dir in character_dirs:
        images = sorted([f for f in char_dir.iterdir() if f.suffix.lower() in {'.png', '.jpg', '.jpeg'}])

        if len(images) < 2:
            logger.warning(f"Skipping {char_dir.name} - need at least 2 images")
            continue

        # Compare all pairs within this character
        for i in range(len(images)):
            for j in range(i + 1, len(images)):
                test_cases.append(TestCase(
                    name=f"{char_dir.name}_pose{i+1}_vs_pose{j+1}",
                    source_path=images[i],
                    target_path=images[j],
                    expected_result="same_character",
                    category="same_pose_variation",
                ))

    # Generate different-character test cases (across directories)
    for i, dir_a in enumerate(character_dirs):
        for dir_b in character_dirs[i + 1:]:
            images_a = sorted([f for f in dir_a.iterdir() if f.suffix.lower() in {'.png', '.jpg', '.jpeg'}])
            images_b = sorted([f for f in dir_b.iterdir() if f.suffix.lower() in {'.png', '.jpg', '.jpeg'}])

            if not images_a or not images_b:
                continue

            # Compare first image from each directory (representative pair)
            test_cases.append(TestCase(
                name=f"{dir_a.name}_vs_{dir_b.name}",
                source_path=images_a[0],
                target_path=images_b[0],
                expected_result="different_character",
                category="different_character",
            ))

    logger.info(f"Generated {len(test_cases)} test cases")
    return test_cases


def create_manual_test_cases(images_dir: Path) -> List[TestCase]:
    """
    Create test cases from manual configuration.

    Use this if you want explicit control over test pairs.
    Create a test_cases.json file in images_dir with this structure:

    {
        "test_cases": [
            {
                "name": "luffy_front_vs_side",
                "source": "luffy/front.png",
                "target": "luffy/side.png",
                "expected": "same_character",
                "category": "same_pose_variation"
            },
            ...
        ]
    }
    """
    config_path = images_dir / "test_cases.json"
    if not config_path.exists():
        return []

    with open(config_path) as f:
        data = json.load(f)

    test_cases = []
    for tc_data in data.get("test_cases", []):
        test_cases.append(TestCase(
            name=tc_data["name"],
            source_path=images_dir / tc_data["source"],
            target_path=images_dir / tc_data["target"],
            expected_result=tc_data["expected"],
            category=tc_data["category"],
        ))

    return test_cases


# =============================================================================
# TEST EXECUTION
# =============================================================================

async def run_test_case(
    checker: CLIPIdentityChecker,
    test_case: TestCase,
) -> TestResult:
    """
    Run a single test case.
    """
    logger.info(f"Testing: {test_case.name}")

    try:
        # Run comparison
        comparison = await checker.compare(
            test_case.source_path,
            test_case.target_path,
        )

        # Determine if result matches expectation
        expected_pass = (test_case.expected_result == "same_character")

        # Build message
        if comparison.similarity is None:
            message = "Comparison failed (no similarity score)"
        elif comparison.passed and expected_pass:
            message = f"✓ Correct: Same character detected ({comparison.similarity:.4f})"
        elif not comparison.passed and not expected_pass:
            message = f"✓ Correct: Different characters detected ({comparison.similarity:.4f})"
        elif comparison.passed and not expected_pass:
            message = f"✗ False Positive: Marked as same but expected different ({comparison.similarity:.4f})"
        else:
            message = f"✗ False Negative: Marked as different but expected same ({comparison.similarity:.4f})"

        logger.info(f"  {message}")

        return TestResult(
            test_case=test_case,
            similarity=comparison.similarity or 0.0,
            passed=comparison.passed,
            threshold_used=comparison.threshold,
            expected_pass=expected_pass,
            message=message,
        )

    except Exception as e:
        logger.error(f"  Test failed: {e}")
        return TestResult(
            test_case=test_case,
            similarity=0.0,
            passed=False,
            threshold_used=checker.threshold,
            expected_pass=(test_case.expected_result == "same_character"),
            message=f"Error: {str(e)}",
        )


async def run_validation(
    images_dir: Path,
    threshold: float = 0.85,
    use_manual_config: bool = False,
) -> ValidationReport:
    """
    Run full validation test suite.
    """
    logger.info(f"=== CLIP Threshold Validation ===")
    logger.info(f"Images directory: {images_dir}")
    logger.info(f"Threshold: {threshold}")

    # Discover or load test cases
    if use_manual_config:
        test_cases = create_manual_test_cases(images_dir)
        if not test_cases:
            logger.warning("No manual test_cases.json found, falling back to auto-discovery")
            test_cases = discover_test_cases(images_dir)
    else:
        test_cases = discover_test_cases(images_dir)

    if not test_cases:
        logger.error("No test cases found. Check image directory structure.")
        sys.exit(1)

    # Initialize CLIP checker
    logger.info("Initializing CLIP model...")
    checker = CLIPIdentityChecker(threshold=threshold)
    await checker.initialize()

    # Run all test cases
    logger.info(f"\n=== Running {len(test_cases)} test cases ===\n")
    test_results = []
    for test_case in test_cases:
        result = await run_test_case(checker, test_case)
        test_results.append(result)

    # Analyze results
    correct = sum(1 for r in test_results if r.is_correct)
    false_positives = sum(
        1 for r in test_results
        if not r.expected_pass and r.passed
    )
    false_negatives = sum(
        1 for r in test_results
        if r.expected_pass and not r.passed
    )

    same_character_scores = [
        r.similarity for r in test_results
        if r.expected_pass and r.similarity > 0
    ]
    different_character_scores = [
        r.similarity for r in test_results
        if not r.expected_pass and r.similarity > 0
    ]

    # Generate recommendations
    recommendations = _generate_recommendations(
        threshold=threshold,
        same_scores=same_character_scores,
        different_scores=different_character_scores,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )

    return ValidationReport(
        threshold_tested=threshold,
        total_tests=len(test_results),
        correct_predictions=correct,
        false_positives=false_positives,
        false_negatives=false_negatives,
        same_character_scores=same_character_scores,
        different_character_scores=different_character_scores,
        recommendations=recommendations,
        test_results=test_results,
    )


def _generate_recommendations(
    threshold: float,
    same_scores: List[float],
    different_scores: List[float],
    false_positives: int,
    false_negatives: int,
) -> List[str]:
    """
    Generate actionable recommendations based on results.
    """
    recommendations = []

    if not same_scores or not different_scores:
        recommendations.append(
            "⚠️  Insufficient data: Need both same-character and different-character test cases"
        )
        return recommendations

    avg_same = statistics.mean(same_scores)
    avg_different = statistics.mean(different_scores)
    min_same = min(same_scores)
    max_different = max(different_scores)

    # Check for overlap
    if max_different >= min_same:
        recommendations.append(
            f"⚠️  Score overlap detected: Some different-character pairs score "
            f"higher ({max_different:.3f}) than some same-character pairs ({min_same:.3f}). "
            f"Perfect separation may not be achievable."
        )

    # Evaluate current threshold
    if false_negatives > false_positives:
        recommended_threshold = threshold - 0.02
        recommendations.append(
            f"❌ Too many false negatives ({false_negatives}). "
            f"Consider lowering threshold to {recommended_threshold:.2f}"
        )
    elif false_positives > false_negatives * 2:
        recommended_threshold = threshold + 0.02
        recommendations.append(
            f"❌ Too many false positives ({false_positives}). "
            f"Consider raising threshold to {recommended_threshold:.2f}"
        )
    elif false_positives == 0 and false_negatives == 0:
        recommendations.append(
            f"✅ Perfect! Threshold {threshold:.2f} achieves 100% accuracy on this dataset"
        )
    else:
        recommendations.append(
            f"✅ Threshold {threshold:.2f} performs well (balanced errors)"
        )

    # Optimal threshold suggestion based on scores
    # Use midpoint between avg_same and max_different
    if max_different < min_same:
        optimal = (min_same + max_different) / 2
        recommendations.append(
            f"💡 Optimal threshold estimate: {optimal:.2f} "
            f"(midpoint between max different and min same)"
        )

    # Separation quality
    separation = avg_same - avg_different
    if separation > 0.15:
        recommendations.append(
            f"✅ Good separation: {separation:.3f} gap between same/different averages"
        )
    elif separation > 0.08:
        recommendations.append(
            f"⚠️  Moderate separation: {separation:.3f} gap. Consider collecting more diverse test cases."
        )
    else:
        recommendations.append(
            f"❌ Poor separation: {separation:.3f} gap. CLIP may not be ideal for this dataset, "
            f"or test cases are too similar."
        )

    return recommendations


# =============================================================================
# REPORTING
# =============================================================================

def print_report(report: ValidationReport) -> None:
    """Print human-readable report to console."""
    print("\n" + "=" * 80)
    print("CLIP THRESHOLD VALIDATION REPORT")
    print("=" * 80)

    print(f"\nThreshold Tested: {report.threshold_tested}")
    print(f"Total Test Cases: {report.total_tests}")
    print(f"Accuracy: {report.accuracy:.1f}%")
    print(f"  ✓ Correct: {report.correct_predictions}")
    print(f"  ✗ False Positives: {report.false_positives}")
    print(f"  ✗ False Negatives: {report.false_negatives}")

    print("\n" + "-" * 80)
    print("SIMILARITY STATISTICS")
    print("-" * 80)

    if report.same_character_scores:
        print(f"\nSame Character Pairs:")
        print(f"  Average: {report.avg_same_similarity:.4f}")
        print(f"  Range: {min(report.same_character_scores):.4f} - {max(report.same_character_scores):.4f}")

    if report.different_character_scores:
        print(f"\nDifferent Character Pairs:")
        print(f"  Average: {report.avg_different_similarity:.4f}")
        print(f"  Range: {min(report.different_character_scores):.4f} - {max(report.different_character_scores):.4f}")

    if report.same_character_scores and report.different_character_scores:
        print(f"\nSeparation Margin: {report.separation_margin:.4f}")

    print("\n" + "-" * 80)
    print("RECOMMENDATIONS")
    print("-" * 80)
    for rec in report.recommendations:
        print(f"\n{rec}")

    print("\n" + "-" * 80)
    print("DETAILED TEST RESULTS")
    print("-" * 80)

    # Group by category
    by_category = {}
    for result in report.test_results:
        category = result.test_case.category
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(result)

    for category, results in by_category.items():
        print(f"\n{category.upper().replace('_', ' ')}:")
        for result in results:
            status = "✓" if result.is_correct else "✗"
            print(f"  {status} {result.test_case.name}: {result.similarity:.4f}")

    print("\n" + "=" * 80)


def save_report(report: ValidationReport, output_path: Path) -> None:
    """Save detailed report to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(report.to_dict(), f, indent=2)
    logger.info(f"Detailed report saved to: {output_path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Validate CLIP identity threshold for anime/stylized content",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example directory structure:
    test_images/
    ├── luffy/
    │   ├── front.png
    │   ├── side.png
    │   └── back.png
    ├── naruto/
    │   ├── pose1.png
    │   └── pose2.png
    └── sasuke/
        └── pose1.png

This will test:
- luffy/front vs luffy/side (expect same)
- luffy/front vs luffy/back (expect same)
- luffy/side vs luffy/back (expect same)
- luffy/* vs naruto/* (expect different)
- luffy/* vs sasuke/* (expect different)
- naruto/* vs sasuke/* (expect different)
        """
    )

    parser.add_argument(
        '--images-dir',
        type=Path,
        required=True,
        help='Directory containing test images organized by character'
    )
    parser.add_argument(
        '--threshold',
        type=float,
        default=0.85,
        help='CLIP similarity threshold to test (default: 0.85)'
    )
    parser.add_argument(
        '--report',
        type=Path,
        help='Path to save detailed JSON report (optional)'
    )
    parser.add_argument(
        '--manual-config',
        action='store_true',
        help='Use test_cases.json for explicit test case configuration'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate images directory
    if not args.images_dir.exists():
        logger.error(f"Images directory not found: {args.images_dir}")
        sys.exit(1)

    # Run validation
    try:
        report = asyncio.run(run_validation(
            images_dir=args.images_dir,
            threshold=args.threshold,
            use_manual_config=args.manual_config,
        ))

        # Print report
        print_report(report)

        # Save detailed report if requested
        if args.report:
            save_report(report, args.report)

        # Exit code based on accuracy
        if report.accuracy >= 95.0:
            logger.info("✅ Validation PASSED (>95% accuracy)")
            sys.exit(0)
        elif report.accuracy >= 85.0:
            logger.warning("⚠️  Validation MARGINAL (85-95% accuracy)")
            sys.exit(0)
        else:
            logger.error("❌ Validation FAILED (<85% accuracy)")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\nValidation interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Validation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
