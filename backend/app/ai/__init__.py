"""PlantIQ AI Subpackage: File Profiling, Column Mapping, and Ingestion Intelligence."""

from backend.app.ai.file_profiler import (
    ColumnStatistic,
    EmptyFileError,
    FileProfileResult,
    FileProfiler,
    ProfilerError,
    TimestampDetectionError,
    TimestampProfile,
    UnsupportedFileFormatError,
    profile_file,
)
from backend.app.ai.ingest_worker import (
    ChannelMappingConfig,
    IngestConfig,
    IngestResult,
    IngestWorker,
    QCFlag,
    evaluate_qc_series,
)
from backend.app.ai.mapping_suggester import (
    CANONICAL_SIGNALS,
    BatchMappingResult,
    MappingSuggester,
    MappingSuggestion,
    suggest_mappings,
    suggest_mappings_async,
)

__all__ = [
    "FileProfiler",
    "profile_file",
    "FileProfileResult",
    "ColumnStatistic",
    "TimestampProfile",
    "ProfilerError",
    "EmptyFileError",
    "UnsupportedFileFormatError",
    "TimestampDetectionError",
    "MappingSuggester",
    "MappingSuggestion",
    "BatchMappingResult",
    "suggest_mappings",
    "suggest_mappings_async",
    "CANONICAL_SIGNALS",
    "IngestWorker",
    "QCFlag",
    "IngestConfig",
    "IngestResult",
    "ChannelMappingConfig",
    "evaluate_qc_series",
]

