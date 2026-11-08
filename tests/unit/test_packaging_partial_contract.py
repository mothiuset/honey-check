"""Contract checks use fictional module reports, never a real executable or inventory."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_executable import Running, assert_hardware_collection

from honey_check.domain.inventory import CollectionStatus, Issue, ModuleReport, ModuleStatus


def document(status: ModuleStatus = ModuleStatus.OK, present: bool = True) -> Any:
    return SimpleNamespace(
        collection=SimpleNamespace(status=CollectionStatus.PARTIAL),
        hardware=SimpleNamespace(
            processor=object() if present else None, memory=object(), storage=object()
        ),
        modules=[
            ModuleReport(
                name=name, status=status if name == "processor" else ModuleStatus.OK, duration_ms=30
            )
            for name in ("processor", "memory", "storage")
        ],
        errors=(
            [Issue(module="processor", code="module_timeout", message="fictional timeout")]
            if status is ModuleStatus.TIMEOUT
            else []
        ),
    )


@pytest.mark.parametrize("status", [ModuleStatus.OK, ModuleStatus.PARTIAL])
def test_successful_hardware_is_still_required_without_timeout(status: ModuleStatus) -> None:
    assert_hardware_collection(document(status))


def test_timeout_requires_absent_section_and_honest_partial_document() -> None:
    assert_hardware_collection(document(ModuleStatus.TIMEOUT, present=False))


@pytest.mark.parametrize("status", [ModuleStatus.OK, ModuleStatus.PARTIAL])
def test_present_hardware_cannot_hide_timeout_diagnostics(status: ModuleStatus) -> None:
    value = document(status)
    value.errors = [Issue(module="processor", code="module_timeout", message="fictional timeout")]
    with pytest.raises(AssertionError):
        assert_hardware_collection(value)


@pytest.mark.parametrize(
    "status", [ModuleStatus.OK, ModuleStatus.PARTIAL, ModuleStatus.FAILED, ModuleStatus.CANCELLED]
)
def test_missing_hardware_without_confirmed_timeout_still_fails(status: ModuleStatus) -> None:
    with pytest.raises(AssertionError):
        assert_hardware_collection(document(status, present=False))


@pytest.mark.parametrize(
    "defect",
    ["no_evidence", "wrong_module", "wrong_code", "claims_complete", "late_section", "no_report"],
)
def test_inconsistent_or_unexplained_timeout_still_fails(defect: str) -> None:
    value = document(ModuleStatus.TIMEOUT, present=False)
    if defect == "no_evidence":
        value.errors = []
    elif defect == "wrong_module":
        value.errors = [Issue(module="memory", code="module_timeout", message="fictional")]
    elif defect == "wrong_code":
        value.errors = [Issue(module="processor", code="unexpected_error", message="fictional")]
    elif defect == "claims_complete":
        value.collection.status = CollectionStatus.COMPLETE
    elif defect == "late_section":
        value.hardware.processor = object()
    elif defect == "no_report":
        value.modules = [report for report in value.modules if report.name != "processor"]
    with pytest.raises(AssertionError):
        assert_hardware_collection(value)


def test_failure_fixture_repr_does_not_include_session_csrf() -> None:
    value = Running(
        process=None,  # type: ignore[arg-type]
        folder=Path("fictional"),
        base="http://127.0.0.1:0",
        port=0,
        opener=None,  # type: ignore[arg-type]
        temp_dir=Path("fictional"),
        csrf="fictional-csrf",
    )
    assert "fictional-csrf" not in repr(value)
