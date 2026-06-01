from src.etl.ingest_professors import run_ingest_professors
from src.etl.ingest_publications import load_all_publications
from src.etl.clean import run_cleaning_pipeline
from src.etl.normalize import run_normalization
from src.etl.enrich_sources import run_enrichment
from src.etl.link_authors import run_author_linking
from src.etl.load import run_full_load

