# Manitoba Tariff Extraction Pipeline

A data extraction and enrichment pipeline for extracting physician billing codes from Manitoba's Payment Schedule.

## Overview

This project extracts and processes 4,600+ physician billing codes from Manitoba's Payment Schedule PDF, applying hierarchical categorization and AI-powered enrichment.

### Features

- **Phase 1: Extraction** - Extracts tariff codes with L1/L2/L3/L4 hierarchy from marked-up source text
- **Phase 2: GPT Enrichment** - AI-powered metadata extraction including:
  - Parent code relationships
  - Add-on fee detection
  - Age and setting restrictions
  - Exclusions and applicable rules

## Project Structure

```
.
├── README.md
├── .gitignore
├── data/
│   ├── mb_payment_schedule_2024_04_01.pdf    # Source PDF (April 1, 2024 edition)
│   └── mb_payment_schedule_marked.txt         # Pre-processed marked-up text
└── notebooks/
    └── mb_tariff_extraction_pipeline.ipynb    # Main extraction pipeline
```

## How It Works

### Input Format

The pipeline requires a **pre-processed marked-up text file** with special markers inserted to indicate document structure. The markers use the format `«MARKER:value»`:

| Marker | Purpose | Example |
|--------|---------|---------|
| `«L1:...»` | Section header (top level) | `«L1:INTEGUMENTARYSYSTEM»` |
| `«L2:...»` | Category (2nd level) | `«L2:CUTANEOUSPROCEDURES»` |
| `«L3:...»` | Subcategory (3rd level) | `«L3:INVESTIGATION»` |
| `«L4:...»` | Sub-subcategory (4th level) | `«L4:BIOPSIES»` |
| `«CODE:XXXX»` | Tariff code | `«CODE:0171»` |
| `«CODE:~XXXX»` | Provisional code | `«CODE:~0171»` |
| `«CODE:XXXX*»` | Asterisked code | `«CODE:0171*»` |

### Phase 1: Rule-Based Extraction

Phase 1 performs deterministic extraction using regex patterns and a state machine:

```
┌─────────────────────────────────────────────────────────────┐
│                    INPUT: Marked-up Text                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  1. Find Content Start                                       │
│     - Skips table of contents and preamble                   │
│     - Locates «L1:RULESOFAPPLICATION» marker                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Hierarchy Tracking (HierarchyTracker class)              │
│     - Maintains current L1/L2/L3/L4 state                    │
│     - Setting a higher level resets all lower levels         │
│     - Example: Setting L2 clears L3 and L4                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Code Block Extraction                                    │
│     - Detects «CODE:XXXX» markers                            │
│     - Collects all lines until next marker                   │
│     - Extracts: description, notes, fees, flags              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Fee Parsing (extract_fee_from_block)                     │
│     - Pattern: "description...fee" (dotted leader)           │
│     - Handles: single fee, TEC/PRO split, unit values        │
│     - Detects "By Report" codes without fixed fees           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  5. Section Code Mapping                                     │
│     - Maps L1 text to standard section codes (A-W)           │
│     - Example: "Integumentary System" → "D"                  │
│     - Example: "Cardiovascular" → "G"                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  OUTPUT: Phase 1 DataFrame                   │
│     4,607 entries with hierarchy, fees, and basic flags      │
└─────────────────────────────────────────────────────────────┘
```

**Key extraction functions:**

- `run_extraction()` - Main loop iterating through lines
- `extract_fee_from_block()` - Parses fee patterns (handles `1,053.59`, TEC/PRO splits, unit values)
- `extract_description()` - Cleans description text, removes markers and fee lines
- `extract_notes()` - Extracts "Notes:" sections
- `get_section_code()` - Maps section names to codes using regex patterns

### Phase 2: GPT Enrichment

Phase 2 sends each entry to GPT for intelligent analysis of relationships and restrictions:

```
┌─────────────────────────────────────────────────────────────┐
│                  INPUT: Phase 1 DataFrame                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  For each entry:                                             │
│                                                              │
│  1. Build Context Window                                     │
│     - 30 lines before, 5 lines after from source             │
│     - Includes surrounding codes for relationship detection  │
│                                                              │
│  2. Send to GPT with structured prompt                       │
│     - Hierarchy info (L1/L2/L3/L4)                           │
│     - Current description and notes                          │
│     - Source context for indentation analysis                │
│                                                              │
│  3. GPT extracts:                                            │
│     - parent_code: Links child codes to parents              │
│     - is_add_on: Identifies supplemental fees                │
│     - add_on_to: Which codes this adds to                    │
│     - age_restriction: Age requirements                      │
│     - setting_restriction: Location requirements             │
│     - exclusions: Billing exclusions                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Checkpointing (every 100 entries)                           │
│  - Saves progress to MB_phase2_checkpoint.json               │
│  - Allows resuming after crashes or API errors               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                OUTPUT: Enriched DataFrame                    │
│     + parent_code, is_add_on, restrictions, exclusions       │
└─────────────────────────────────────────────────────────────┘
```

**Parent Code Detection:**

The Manitoba manual uses indentation to show procedure relationships:
```
0865    Femur, neck, closed reduction           → parent_code: null
0868       open reduction                       → parent_code: "0865"
0870          prosthetic replacement            → parent_code: "0868"
```

GPT analyzes whitespace in the source context to build these chains.

**Add-On vs. Child Code Distinction:**

| Pattern | Classification | Example |
|---------|---------------|---------|
| Ends with ", Add" | Add-on (`is_add_on: true`) | "Coronary Thrombectomy, Add" |
| Indented under another | Child (`parent_code` set) | "open reduction" under "Femur, neck" |
| "Day 2-10, per day" | Variant (`parent_code` to Day 1) | Tiered billing codes |

### Configuration

Key constants in the notebook:

```python
# Extraction settings
CONTENT_START_MARKER = '«L1:RULESOFAPPLICATION»'  # Where to begin parsing
HIERARCHY_LOOKAHEAD_LINES = 5                      # Lines to search for hierarchy text

# GPT settings
GPT_MODEL = "gpt-5.2"
GPT_TEMPERATURE = 0          # Deterministic output
API_CALL_DELAY_SECONDS = 0.1 # Rate limiting

# Checkpointing
CHECKPOINT_INTERVAL = 100    # Save every N entries
CHECKPOINT_FILE = 'MB_phase2_checkpoint.json'
```

### Section Code Mappings

| Section Code | Body System |
|--------------|-------------|
| A | Visits/Examinations |
| B | General Schedule |
| C | Anesthesia |
| D | Integumentary (Skin, Breast) |
| E | Musculoskeletal |
| F | Respiratory |
| G | Cardiovascular |
| H | Digestive |
| I | Urinary |
| J | Male Genital |
| K | Female Genital/Obstetric |
| L | Maternity |
| M | Endocrine |
| N | Nervous System |
| O | Eye/Ocular |
| P | Ear |
| Q | Nose/Nasal |
| T | Diagnostic Radiology |
| U | Nuclear Medicine |
| V | Therapeutic Radiology |
| W | Laboratory |

## Requirements

- Python 3.8+
- Google Colab (recommended) or Jupyter environment
- OpenAI API key (for Phase 2 enrichment)

### Python Dependencies

```
openai
pandas
```

## Usage

1. Open `notebooks/mb_tariff_extraction_pipeline.ipynb` in Google Colab or Jupyter
2. Upload the marked-up text file (`data/mb_payment_schedule_marked.txt`)
3. Run Phase 1 to extract base tariff codes
4. (Optional) Configure and run Phase 2 for GPT enrichment

### Test Mode

For development/testing, set `TEST_MODE = True` and configure filters:

```python
TEST_MODE = True
TEST_CATEGORY = "Lower Extremity"  # Filter by L2 category
TEST_SECTION = "Musculoskeletal"   # Filter by L1 section
TEST_CODE_START = "0865"           # Filter by code range
TEST_CODE_END = "0930"
TEST_CODES = ["0865", "0868"]      # Filter by specific codes
TEST_LIMIT = 50                    # Fallback: first N entries
```

### Output

The pipeline generates:

- `mb_tariffs_phase1.csv` - Basic extraction with hierarchy
- `mb_tariffs_enriched.csv` - Full enriched dataset with GPT metadata

### Output Schema

| Column | Description |
|--------|-------------|
| `tariff_code` | 4-digit billing code |
| `tariff_code_display` | Display format with provisional (~) and asterisk (*) markers |
| `parent_code` | Related parent code for hierarchical procedures |
| `section_code` | Section letter (A-W) |
| `section_name` | L1 hierarchy level |
| `specialty_code` | Specialty identifier |
| `specialty_name` | Specialty name |
| `category` | L2 hierarchy level |
| `subcategory` | L3 hierarchy level |
| `subsubcategory` | L4 hierarchy level |
| `description` | Procedure description |
| `notes` | Additional notes from source |
| `fee_total` | Total fee amount |
| `fee_technical` | Technical component (if split) |
| `fee_professional` | Professional component (if split) |
| `unit_value` | Relative value unit |
| `is_add_on` | Whether this is a supplemental add-on fee |
| `add_on_to` | Codes this add-on applies to |
| `age_restriction` | Age requirements |
| `setting_restriction` | Location/setting requirements |
| `exclusions` | Billing exclusions |
| `is_provisional` | Provisional code flag (~) |
| `is_asterisked` | Asterisked code flag (*) |
| `is_by_report` | Fee determined by report |
| `is_cross_reference` | References another section |
| `cross_reference_to` | Target of cross-reference |
| `applicable_rules` | Referenced rule numbers |
| `time_requirement_minutes` | Minimum time requirement |

## Data Source

Manitoba Health Physician's Manual of Fees - Payment Schedule (April 1, 2024)

## License

For authorized use only. Refer to Manitoba Health guidelines for data usage restrictions.
