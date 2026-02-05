# Saskatchewan Payment Schedule Tagging Prompt

## Task

You are tagging the Saskatchewan Payment Schedule for Insured Services Provided by a Physician (April 1, 2024). Apply structural markers to identify hierarchy levels and billing codes.

---

## Tagging Convention

| Marker | Purpose | Example |
|--------|---------|---------|
| `«L1:....»` | Section header (top level) | `«L1:SECTION A – General Services»` |
| `«L2:....»` | Category (2nd level) | `«L2:Botox Injections»` |
| `«L3:....»` | Subcategory (3rd level) | `«L3:Tongue»` |
| `«L4:....»` | Sub-subcategory (4th level) | `«L4:Glossectomy procedures»` |
| `«CODE:XXXX»` | Tariff code | `«CODE:70A»` |
| `«CODE:~XXXX»` | Provisional code (tilde prefix) | `«CODE:~153A»` |
| `«CODE:XXXX*»` | Asterisked code | `«CODE:5B*»` |

---

## Structural Recognition Rules

### L1 (Section Headers)
Apply `«L1:....»` to:
- Main section headers formatted as "S E C T I O N [Letter] – [Name]"
- Major introductory sections in ALL CAPS (INTRODUCTION, DEFINITIONS, ASSESSMENT RULES, etc.)
- The document title on first appearance

**Pattern:** Spaced "S E C T I O N" followed by letter A-Y and section name.

### L2 (Categories)
Apply `«L2:....»` to:
- Named subsections within a section (bold or standalone text on its own line, no billing code prefix)
- Sub-sections within introductory material (e.g., "Visit Services" under Assessment Rules)
- Major clinical groupings (e.g., "Emergency Resuscitation - 'Code' Situations", "Cardiac Catheterization", "Echocardiography")

**Indicators:** Appears before a group of related billing codes; may have numbered rules following it.

### L3 (Subcategories)
Apply `«L3:....»` to:
- Anatomical region groupings within surgical sections (e.g., "Head and Neck", "Thorax", "Tongue")
- Procedure type groupings (e.g., "First Trimester", "Doppler Studies")
- Specific clinical categories within an L2 grouping

**Indicators:** Nested under an L2 category; groups related procedures by body part or type.

### L4 (Sub-subcategories)
Apply `«L4:....»` to:
- Further subdivisions within L3 categories
- Named procedure groupings at the finest level before individual codes
- Rarely used; only when clear fourth-level hierarchy exists

### Billing Codes
Apply code markers to every billable service code:

**Standard codes:** `«CODE:XXXX»`
- Format: 1-4 digits followed by section letter (e.g., 70A, 153A, 918A, 5B, 100X)
- Appears at start of line before description

**Asterisked codes:** `«CODE:XXXX*»`
- Codes marked with * in the source (indicates automatic age supplement applies)
- The asterisk appears after the fee amount in source, attach it to the code marker

**Provisional/Restricted codes:** `«CODE:~XXXX»`
- Codes marked with @ or # in the source (requires entitlement or special approval)
- Use tilde (~) prefix to indicate restricted status

---

## Code Line Recognition

### Standard Pattern
```
[Code][Letter]    [Description]    $[Fee]    $[Fee]    [Class]    [Anes]
```

### Examples to Tag

**Simple code:**
```
Source: 70A     Telephone call from an SGI Driver Medical Review Unit...    $30.00    $30.00
Tagged: «CODE:70A» Telephone call from an SGI Driver Medical Review Unit...    $30.00    $30.00
```

**Asterisked code (age supplement applies):**
```
Source: 5B      Partial assessment...    $43.05*
Tagged: «CODE:5B*» Partial assessment...    $43.05
```

**Restricted code (requires approval):**
```
Source: 41A     FASD assessment...    $45.85@    $45.85@
Tagged: «CODE:~41A» FASD assessment...    $45.85    $45.85
```

**Code with # symbol (requires listing):**
```
Source: 320A    -- technical - first    $55.00#    D
Tagged: «CODE:~320A» -- technical - first    $55.00    D
```

---

## Section-Specific Guidance

### Section A (General Services)
Common L2 categories: SGI Medical Driver Fitness Review, Exception Drug Status, Procedures, Communicable Disease Services, Allergy Diagnosis, Botox Injections, Emergency Resuscitation, Cardiac Catheterization, Echocardiography, Special Care Home Management, Surcharges, Emergency Room Coverage, Palliative Care Services, Hyperbaric Oxygen Therapy

### Section B (General Practice)
L2 categories: General Practice Visits, Hospital Care, Counselling, Procedures, Virtual Care Services

### Sections C-T (Specialist Sections)
Typical L2 structure: Visits, Hospital Care, Virtual Care Services, Procedures
L3 level: Anatomical groupings within Procedures

### Section V (Laboratory Medicine)
L2 categories: Hematology, Chemistry, Microbiology, etc.
L3 categories: Specific test groupings

### Sections W, X (Imaging)
L2 categories by anatomical region
L3 categories by specific exam type

---

## Do NOT Tag

- Page headers ("Payment Schedule for Insured Services Provided by a Physician")
- Page footers ("April 1, 2024    Page X")
- Column headers (Specialist, General Practitioner, Class, Anes, etc.)
- "BLANK PAGE INTENTIONAL" markers
- Explanatory codes in front matter (AA, AB, etc. - these are rejection codes, not billing codes)
- Narrative rules text (keep as plain text)
- Fee amounts, class codes (D, 0, 10, 42), anesthesia codes (L, M, H)

---

## Output Format

Return the tagged text preserving original structure. Insert markers at the beginning of relevant lines:

```
«L1:SECTION A – General Services»

«L2:SGI Medical Driver Fitness Review»

1. The services listed on this page are paid by MSB on an agency basis for SGI.
2. These codes are not eligible for any additional charges...

«CODE:70A» Telephone call from an SGI Driver Medical Review Unit...    $30.00    $30.00

«CODE:71A» Written letter or facsimile requested by an SGI Driver...    $55.00    $55.00

«CODE:74A» Examination and Report requested by the SGI Driver...    $140.00    $75.00

«L2:Exception Drug Status»

«CODE:153A» Multiple Sclerosis    $30.40    $30.40
```

---

## Processing Instructions

1. Read the 10 pages of content provided
2. Identify the current section context (which Section letter, which L2 category)
3. Apply L1-L4 markers to structural headers
4. Apply CODE markers to every billing code line
5. Preserve all other text unchanged
6. Maintain original line breaks and spacing
7. If a page continues mid-section, note the context and continue tagging appropriately

---

## Quality Checks

Before submitting:
- Every billing code (digits + letter pattern) should have a CODE marker
- L1 markers appear only at section boundaries
- L2 markers appear at major subsection headers
- No duplicate markers on the same element
- Asterisked codes (*) and restricted codes (@, #) are properly marked
