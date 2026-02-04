#!/usr/bin/env python3
"""
PDF Text Marker - Converts PDF payment schedules to marked-up text format.

This script extracts text from PDF files and inserts hierarchy markers
that can be processed by the tariff extraction pipeline.

Marker Format:
    «L1:SECTIONNAME»     - Top-level section header
    «L2:CATEGORY»        - 2nd-level category
    «L3:SUBCATEGORY»     - 3rd-level subcategory
    «L4:DETAIL»          - 4th-level detail
    «CODE:XXXX»          - Tariff code (4 digits)
    «CODE:~XXXX»         - Provisional code
    «CODE:XXXX*»         - Asterisked code

Usage:
    python pdf_text_marker.py input.pdf -o output_marked.txt
    python pdf_text_marker.py input.pdf --config custom_config.json
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Tuple, Any

# Try to import PDF libraries - support multiple backends
PDF_BACKEND = None

try:
    import fitz  # PyMuPDF
    PDF_BACKEND = 'pymupdf'
except ImportError:
    pass

if PDF_BACKEND is None:
    try:
        import pdfplumber
        PDF_BACKEND = 'pdfplumber'
    except ImportError:
        pass

if PDF_BACKEND is None:
    print("Error: No PDF library found. Install one of:")
    print("  pip install pymupdf    (recommended)")
    print("  pip install pdfplumber")
    sys.exit(1)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class MarkerConfig:
    """Configuration for PDF parsing and marker detection."""

    # Font size thresholds for hierarchy detection (relative to body text)
    l1_min_font_size: float = 12.0  # Section headers typically larger
    l2_min_font_size: float = 10.5
    l3_min_font_size: float = 10.0

    # Patterns indicating hierarchy levels
    l1_patterns: List[str] = field(default_factory=lambda: [
        r'^[A-Z][A-Z\s\-]+\s*\(\d{2}(?:-\d+)?\)',  # "NEUROLOGY (01-1)"
        r'^[A-Z][A-Z\s\-]{10,}$',  # ALL CAPS headers (10+ chars)
        r'^(?:VISITS|GENERAL|ANESTHESIA|INTEGUMENTARY|MUSCULOSKELETAL)',
        r'^(?:RESPIRATORY|CARDIOVASCULAR|DIGESTIVE|URINARY)',
        r'^(?:NERVOUS|ENDOCRINE|MATERNITY|LABORATORY)',
    ])

    l2_patterns: List[str] = field(default_factory=lambda: [
        r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*(?:Procedures?|Care|Visits?|Services?)',
        r'^(?:Office|Hospital|Virtual|Chronic|Concomitant)',
        r'^(?:Investigation|Incision|Excision|Repair)',
    ])

    l3_patterns: List[str] = field(default_factory=lambda: [
        r'^[A-Z][a-z]+(?:\s+[A-Za-z]+)*$',  # Title case subsections
    ])

    # Tariff code patterns
    code_pattern: str = r'^[~]?(\d{4})[\*]?\s+'
    code_with_fee_pattern: str = r'^[~]?(\d{4})[\*]?\s+.+?\.{3,}\s*[\d,]+\.\d{2}'
    provisional_marker: str = '~'
    asterisk_marker: str = '*'

    # Fee patterns
    fee_pattern: str = r'\.{3,}\s*([\d,]+\.\d{2})'

    # Page header/footer patterns to skip
    skip_patterns: List[str] = field(default_factory=lambda: [
        r'^April 1,\s*\d{4}',  # Date headers
        r'^[A-Z]-\d+$',  # Page numbers like "A-1"
        r'^\d{1,3}$',  # Plain page numbers (1-3 digits only, not 4-digit tariff codes)
        r'^[ivxlcdm]+$',  # Roman numeral page numbers
        r'^Table of Contents',
        r'^\f',  # Form feed
    ])

    # Content start patterns (skip table of contents, etc.)
    content_start_patterns: List[str] = field(default_factory=lambda: [
        r'RULES\s+OF\s+APPLICATION',
        r'These benefits cannot be correctly interpreted',
    ])

    # Minimum line length to consider
    min_line_length: int = 3

    # Output format
    marker_format: str = '«{type}:{value}»'
    code_marker_format: str = '«CODE:{prefix}{code}{suffix}»'


def load_config(config_path: Optional[str] = None) -> MarkerConfig:
    """Load configuration from file or use defaults."""
    if config_path and Path(config_path).exists():
        with open(config_path, 'r') as f:
            config_dict = json.load(f)
        return MarkerConfig(**config_dict)
    return MarkerConfig()


# =============================================================================
# TEXT EXTRACTION
# =============================================================================

@dataclass
class TextLine:
    """Represents a line of text with metadata."""
    text: str
    page_num: int
    top: float  # Y position from top
    left: float  # X position (indentation)
    font_size: float = 0.0
    is_bold: bool = False
    line_num: int = 0


def extract_text_with_layout(pdf_path: str) -> List[TextLine]:
    """
    Extract text from PDF while preserving layout information.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        List of TextLine objects with position and formatting info
    """
    if PDF_BACKEND == 'pymupdf':
        return _extract_with_pymupdf(pdf_path)
    else:
        return _extract_with_pdfplumber(pdf_path)


def _extract_with_pymupdf(pdf_path: str) -> List[TextLine]:
    """Extract text using PyMuPDF (fitz)."""
    lines = []
    line_num = 0

    print(f"Opening PDF: {pdf_path} (using PyMuPDF)")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"Total pages: {total_pages}")

    for page_num, page in enumerate(doc, 1):
        if page_num % 50 == 0:
            print(f"  Processing page {page_num}/{total_pages}...")

        # Get text with detailed information
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        for block in blocks:
            if block["type"] != 0:  # Skip non-text blocks
                continue

            for line_data in block.get("lines", []):
                spans = line_data.get("spans", [])
                if not spans:
                    continue

                # Combine spans into line text
                text_parts = []
                font_sizes = []
                is_bold = False

                for span in spans:
                    text_parts.append(span.get("text", ""))
                    font_sizes.append(span.get("size", 10))
                    font_name = span.get("font", "").lower()
                    if "bold" in font_name:
                        is_bold = True

                line_text = "".join(text_parts)
                if not line_text.strip():
                    continue

                avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 10.0
                bbox = line_data.get("bbox", (0, 0, 0, 0))

                line_num += 1
                lines.append(TextLine(
                    text=line_text,
                    page_num=page_num,
                    top=bbox[1],
                    left=bbox[0],
                    font_size=avg_font_size,
                    is_bold=is_bold,
                    line_num=line_num
                ))

    doc.close()
    print(f"Extracted {len(lines)} lines of text")
    return lines


def _extract_with_pdfplumber(pdf_path: str) -> List[TextLine]:
    """Extract text using pdfplumber."""
    lines = []
    line_num = 0

    print(f"Opening PDF: {pdf_path} (using pdfplumber)")

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"Total pages: {total_pages}")

        for page_num, page in enumerate(pdf.pages, 1):
            if page_num % 50 == 0:
                print(f"  Processing page {page_num}/{total_pages}...")

            # Extract text with character-level info
            chars = page.chars
            if not chars:
                # Fallback to simple text extraction
                text = page.extract_text()
                if text:
                    for line_text in text.split('\n'):
                        line_num += 1
                        lines.append(TextLine(
                            text=line_text,
                            page_num=page_num,
                            top=0,
                            left=0,
                            line_num=line_num
                        ))
                continue

            # Group characters into lines based on Y position
            current_line_chars = []
            current_top = None
            tolerance = 3  # Y tolerance for same line

            # Sort characters by position
            sorted_chars = sorted(chars, key=lambda c: (c['top'], c['x0']))

            for char in sorted_chars:
                char_top = char['top']

                if current_top is None:
                    current_top = char_top
                    current_line_chars = [char]
                elif abs(char_top - current_top) <= tolerance:
                    current_line_chars.append(char)
                else:
                    # New line - save current line
                    if current_line_chars:
                        line_text, font_size, is_bold, left = _process_char_line(current_line_chars)
                        if line_text.strip():
                            line_num += 1
                            lines.append(TextLine(
                                text=line_text,
                                page_num=page_num,
                                top=current_top,
                                left=left,
                                font_size=font_size,
                                is_bold=is_bold,
                                line_num=line_num
                            ))
                    current_top = char_top
                    current_line_chars = [char]

            # Don't forget the last line
            if current_line_chars:
                line_text, font_size, is_bold, left = _process_char_line(current_line_chars)
                if line_text.strip():
                    line_num += 1
                    lines.append(TextLine(
                        text=line_text,
                        page_num=page_num,
                        top=current_top,
                        left=left,
                        font_size=font_size,
                        is_bold=is_bold,
                        line_num=line_num
                    ))

    print(f"Extracted {len(lines)} lines of text")
    return lines


def _process_char_line(chars: List[Dict]) -> Tuple[str, float, bool, float]:
    """
    Process a list of characters into a line of text with metadata.

    Returns:
        Tuple of (text, avg_font_size, is_bold, left_position)
    """
    if not chars:
        return '', 0.0, False, 0.0

    # Sort by x position
    chars = sorted(chars, key=lambda c: c['x0'])

    # Build text with spacing
    text_parts = []
    prev_x1 = None

    for char in chars:
        if prev_x1 is not None:
            gap = char['x0'] - prev_x1
            if gap > 3:  # Add space for gaps
                text_parts.append(' ')
        text_parts.append(char.get('text', ''))
        prev_x1 = char['x1']

    text = ''.join(text_parts)

    # Calculate average font size
    sizes = [c.get('size', 10) for c in chars if c.get('size')]
    avg_size = sum(sizes) / len(sizes) if sizes else 10.0

    # Check for bold (font name contains 'Bold' or 'bold')
    fonts = [c.get('fontname', '') for c in chars]
    is_bold = any('bold' in f.lower() for f in fonts)

    # Left position
    left = chars[0]['x0'] if chars else 0.0

    return text, avg_size, is_bold, left


# =============================================================================
# HIERARCHY DETECTION
# =============================================================================

class HierarchyDetector:
    """Detects document hierarchy levels based on text patterns and formatting."""

    def __init__(self, config: MarkerConfig):
        self.config = config
        self.l1_patterns = [re.compile(p, re.IGNORECASE) for p in config.l1_patterns]
        self.l2_patterns = [re.compile(p, re.IGNORECASE) for p in config.l2_patterns]
        self.l3_patterns = [re.compile(p, re.IGNORECASE) for p in config.l3_patterns]
        self.skip_patterns = [re.compile(p, re.IGNORECASE) for p in config.skip_patterns]
        self.code_pattern = re.compile(config.code_pattern)
        self.code_with_fee = re.compile(config.code_with_fee_pattern)
        self.fee_pattern = re.compile(config.fee_pattern)

    def should_skip(self, line: TextLine) -> bool:
        """Check if line should be skipped (headers, footers, etc.)."""
        text = line.text.strip()
        if len(text) < self.config.min_line_length:
            return True
        for pattern in self.skip_patterns:
            if pattern.search(text):
                return True
        return False

    def detect_level(self, line: TextLine, prev_line: Optional[TextLine] = None) -> Optional[str]:
        """
        Detect hierarchy level of a line.

        Returns:
            'L1', 'L2', 'L3', 'L4', 'CODE', or None
        """
        text = line.text.strip()

        # Check for tariff code first
        if self._is_tariff_code(text):
            return 'CODE'

        # Check L1 patterns (highest priority)
        if self._matches_l1(line):
            return 'L1'

        # Check L2 patterns
        if self._matches_l2(line):
            return 'L2'

        # Check L3 patterns
        if self._matches_l3(line):
            return 'L3'

        return None

    def _is_tariff_code(self, text: str) -> bool:
        """Check if line is or starts with a tariff code."""
        text = text.strip()

        # Pattern 1: Code with fee on same line "8540 Description ....... 112.42"
        if self.code_with_fee.match(text):
            return True

        # Pattern 2: Standalone code (just 4 digits, optionally with ~ or *)
        # e.g., "8540" or "~0171" or "8540*"
        if re.match(r'^[~]?\d{4}[\*]?\s*$', text):
            return True

        # Pattern 3: Code at start with description but maybe fee on next line
        # e.g., "8540 Complete History and Physical Examination"
        match = re.match(r'^[~]?(\d{4})[\*]?\s+(.+)$', text)
        if match:
            remaining = match.group(2).strip()
            # Skip index entries (have page refs like "C-19, D-1")
            if re.match(r'^\.{3,}\s*[A-Z]-\d+', remaining):
                return False
            # Skip if remaining is just page references
            if re.match(r'^[A-Z]-\d+(?:,\s*[A-Z]-\d+)*\s*$', remaining):
                return False
            # Has meaningful description
            if len(remaining) > 10:
                return True

        return False

    def _matches_l1(self, line: TextLine) -> bool:
        """Check if line matches L1 section header patterns."""
        text = line.text.strip()

        # Skip if line is too long (headers are typically short)
        if len(text) > 80:
            return False

        # Skip if line has a fee pattern (it's a tariff line, not a header)
        if self.fee_pattern.search(text):
            return False

        # Skip if line starts with a code
        if self.code_pattern.match(text):
            return False

        # Strong L1: ALL CAPS + specialty code pattern like "NEUROLOGY (01-1)"
        if re.search(r'^[A-Z][A-Z\s\-/]+\s*\(\d{2}(?:-\d+)?\)\s*$', text):
            return True

        # Strong L1: Major body system names (specific patterns)
        major_sections = [
            r'^VISITS/EXAMINATIONS',
            r'^GENERAL\s+SCHEDULE',
            r'^ANESTHESIA',
            r'^INTEGUMENTARY\s+SYSTEM',
            r'^MUSCULOSKELETAL\s+SYSTEM',
            r'^RESPIRATORY\s+SYSTEM',
            r'^CARDIOVASCULAR\s+SYSTEM',
            r'^DIGESTIVE\s+SYSTEM',
            r'^URINARY\s+SYSTEM',
            r'^NERVOUS\s+SYSTEM',
            r'^ENDOCRINE\s+SYSTEM',
            r'^MATERNITY',
            r'^LABORATORY',
            r'^DIAGNOSTIC\s+RADIOLOGICAL',
            r'^NUCLEAR\s+MEDICINE',
            r'^THERAPEUTIC\s+RADIOLOGICAL',
            r'^RULES\s+OF\s+APPLICATION',
        ]
        for pattern in major_sections:
            if re.search(pattern, text, re.IGNORECASE):
                return True

        # Large font + ALL CAPS + short text (but not too short)
        if line.font_size >= self.config.l1_min_font_size:
            if text.isupper() and 15 < len(text) < 60:
                # Additional check: should look like a section title
                words = text.split()
                if 2 <= len(words) <= 6:
                    return True

        return False

    def _matches_l2(self, line: TextLine) -> bool:
        """Check if line matches L2 category patterns."""
        text = line.text.strip()

        # Skip if too long or has fee
        if len(text) > 60 or self.fee_pattern.search(text):
            return False

        # Skip if starts with code
        if self.code_pattern.match(text):
            return False

        # Specific L2 patterns for medical schedules
        l2_specific = [
            r'^Office,?\s*Home\s*Visits?',
            r'^Hospital\s+Care',
            r'^Virtual\s+Visits?',
            r'^Chronic\s+Care',
            r'^Concomitant\s+Care',
            r'^Cutaneous\s+Procedures?',
            r'^Upper\s+Extremity',
            r'^Lower\s+Extremity',
            r'^Spine',
            r'^Head\s+and\s+Neck',
            r'^Pelvis',
            r'^Thorax',
            r'^Abdomen',
        ]

        for pattern in l2_specific:
            if re.search(pattern, text, re.IGNORECASE):
                return True

        # Bold + Title Case + short
        if line.is_bold and line.font_size >= self.config.l2_min_font_size:
            # Check if it's Title Case (not ALL CAPS, not lowercase)
            words = text.split()
            if 2 <= len(words) <= 5:
                title_words = sum(1 for w in words if w[0].isupper() and not w.isupper())
                if title_words >= len(words) * 0.5:
                    return True

        return False

    def _matches_l3(self, line: TextLine) -> bool:
        """Check if line matches L3 subcategory patterns."""
        text = line.text.strip()

        # Skip if too long, has fee, or starts with code
        if len(text) > 40 or self.fee_pattern.search(text):
            return False
        if self.code_pattern.match(text):
            return False

        # Specific L3 patterns
        l3_specific = [
            r'^Investigation$',
            r'^Incision$',
            r'^Excision$',
            r'^Repair$',
            r'^Revision\s+and\s+Repair$',
            r'^Reconstruction$',
            r'^Amputation$',
            r'^Fractures?$',
            r'^Dislocations?$',
            r'^Joint\s+Procedures?$',
        ]

        for pattern in l3_specific:
            if re.search(pattern, text, re.IGNORECASE):
                return True

        return False

    def extract_code_info(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extract tariff code information from a line.

        Returns:
            Dict with code, is_provisional, is_asterisked, or None
        """
        text = text.strip()

        # Pattern 1: Standalone code "8540" or "~0171" or "8540*"
        match = re.match(r'^(~)?(\d{4})(\*)?\s*$', text)
        if match:
            return {
                'code': match.group(2),
                'is_provisional': match.group(1) == '~',
                'is_asterisked': match.group(3) == '*',
                'full_match': match.group(0),
            }

        # Pattern 2: Code with description "8540 Description..."
        match = re.match(r'^(~)?(\d{4})(\*)?\s+', text)
        if match:
            return {
                'code': match.group(2),
                'is_provisional': match.group(1) == '~',
                'is_asterisked': match.group(3) == '*',
                'full_match': match.group(0),
            }

        return None


# =============================================================================
# MARKER INSERTION
# =============================================================================

class TextMarker:
    """Inserts hierarchy markers into extracted text."""

    def __init__(self, config: MarkerConfig):
        self.config = config
        self.detector = HierarchyDetector(config)

    def mark_text(self, lines: List[TextLine]) -> List[str]:
        """
        Process lines and insert appropriate markers.

        Args:
            lines: List of TextLine objects from PDF extraction

        Returns:
            List of marked-up text lines
        """
        output = []
        content_started = False
        content_start_patterns = [re.compile(p) for p in self.config.content_start_patterns]

        print("Inserting markers...")

        current_hierarchy = {'L1': '', 'L2': '', 'L3': '', 'L4': ''}

        for i, line in enumerate(lines):
            text = line.text

            # Check if we should start processing content
            if not content_started:
                for pattern in content_start_patterns:
                    if pattern.search(text):
                        content_started = True
                        # Insert L1 marker for Rules of Application
                        marker = self._format_marker('L1', 'RULESOFAPPLICATION')
                        output.append(marker)
                        output.append(text)
                        break
                else:
                    # Still in preamble - output as-is
                    output.append(text)
                continue

            # Skip headers/footers
            if self.detector.should_skip(line):
                output.append(text)
                continue

            # Get previous line for context
            prev_line = lines[i - 1] if i > 0 else None

            # Detect hierarchy level
            level = self.detector.detect_level(line, prev_line)

            if level == 'CODE':
                # Insert code marker
                code_info = self.detector.extract_code_info(text)
                if code_info:
                    marker = self._format_code_marker(
                        code_info['code'],
                        code_info['is_provisional'],
                        code_info['is_asterisked']
                    )
                    output.append(marker)

            elif level in ('L1', 'L2', 'L3', 'L4'):
                # Insert hierarchy marker
                header_text = self._clean_header_text(text)
                marker = self._format_marker(level, header_text)
                output.append(marker)

                # Update current hierarchy and reset lower levels
                current_hierarchy[level] = header_text
                level_num = int(level[1])
                for l in range(level_num + 1, 5):
                    current_hierarchy[f'L{l}'] = ''

            # Always output the original text
            output.append(text)

        return output

    def _format_marker(self, level: str, text: str) -> str:
        """Format a hierarchy marker."""
        # Clean and normalize the text for marker
        clean_text = re.sub(r'\s+', '', text.upper())
        clean_text = re.sub(r'[^A-Z0-9]', '', clean_text)
        return self.config.marker_format.format(type=level, value=clean_text)

    def _format_code_marker(self, code: str, is_provisional: bool, is_asterisked: bool) -> str:
        """Format a tariff code marker."""
        prefix = '~' if is_provisional else ''
        suffix = '*' if is_asterisked else ''
        return self.config.code_marker_format.format(
            prefix=prefix,
            code=code,
            suffix=suffix
        )

    def _clean_header_text(self, text: str) -> str:
        """Clean header text for use in markers."""
        # Remove trailing dots, page numbers, etc.
        text = re.sub(r'\.{2,}.*$', '', text)
        text = re.sub(r'\s+[A-Z]-\d+$', '', text)
        return text.strip()


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def process_pdf(
    input_path: str,
    output_path: str,
    config: Optional[MarkerConfig] = None
) -> None:
    """
    Process a PDF file and create marked-up text output.

    Args:
        input_path: Path to input PDF file
        output_path: Path to output text file
        config: Optional configuration object
    """
    if config is None:
        config = MarkerConfig()

    # Extract text with layout info
    lines = extract_text_with_layout(input_path)

    # Insert markers
    marker = TextMarker(config)
    marked_lines = marker.mark_text(lines)

    # Write output
    print(f"Writing output to: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        for line in marked_lines:
            f.write(line + '\n')

    # Print statistics
    stats = _calculate_stats(marked_lines, config)
    print("\n" + "=" * 50)
    print("CONVERSION STATISTICS")
    print("=" * 50)
    print(f"Total lines: {len(marked_lines):,}")
    print(f"L1 markers: {stats['L1']:,}")
    print(f"L2 markers: {stats['L2']:,}")
    print(f"L3 markers: {stats['L3']:,}")
    print(f"L4 markers: {stats['L4']:,}")
    print(f"CODE markers: {stats['CODE']:,}")
    print(f"  - Provisional (~): {stats['provisional']:,}")
    print(f"  - Asterisked (*): {stats['asterisked']:,}")


def _calculate_stats(lines: List[str], config: MarkerConfig) -> Dict[str, int]:
    """Calculate statistics about inserted markers."""
    stats = {'L1': 0, 'L2': 0, 'L3': 0, 'L4': 0, 'CODE': 0, 'provisional': 0, 'asterisked': 0}

    for line in lines:
        if '«L1:' in line:
            stats['L1'] += 1
        elif '«L2:' in line:
            stats['L2'] += 1
        elif '«L3:' in line:
            stats['L3'] += 1
        elif '«L4:' in line:
            stats['L4'] += 1
        elif '«CODE:' in line:
            stats['CODE'] += 1
            if '«CODE:~' in line:
                stats['provisional'] += 1
            if '*»' in line:
                stats['asterisked'] += 1

    return stats


def save_default_config(path: str) -> None:
    """Save default configuration to a JSON file."""
    config = MarkerConfig()
    config_dict = {
        'l1_min_font_size': config.l1_min_font_size,
        'l2_min_font_size': config.l2_min_font_size,
        'l3_min_font_size': config.l3_min_font_size,
        'l1_patterns': config.l1_patterns,
        'l2_patterns': config.l2_patterns,
        'l3_patterns': config.l3_patterns,
        'code_pattern': config.code_pattern,
        'code_with_fee_pattern': config.code_with_fee_pattern,
        'fee_pattern': config.fee_pattern,
        'skip_patterns': config.skip_patterns,
        'content_start_patterns': config.content_start_patterns,
        'min_line_length': config.min_line_length,
    }
    with open(path, 'w') as f:
        json.dump(config_dict, f, indent=2)
    print(f"Default configuration saved to: {path}")


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description='Convert PDF payment schedules to marked-up text format.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic conversion
    python pdf_text_marker.py input.pdf -o output_marked.txt

    # With custom configuration
    python pdf_text_marker.py input.pdf -o output.txt --config my_config.json

    # Generate default config file for customization
    python pdf_text_marker.py --save-config default_config.json

Marker Format:
    «L1:SECTIONNAME»     - Top-level section header
    «L2:CATEGORY»        - 2nd-level category
    «L3:SUBCATEGORY»     - 3rd-level subcategory
    «L4:DETAIL»          - 4th-level detail
    «CODE:XXXX»          - Tariff code (4 digits)
    «CODE:~XXXX»         - Provisional code
    «CODE:XXXX*»         - Asterisked code
        """
    )

    parser.add_argument(
        'input',
        nargs='?',
        help='Input PDF file path'
    )

    parser.add_argument(
        '-o', '--output',
        help='Output text file path (default: input_marked.txt)'
    )

    parser.add_argument(
        '-c', '--config',
        help='Path to JSON configuration file'
    )

    parser.add_argument(
        '--save-config',
        metavar='PATH',
        help='Save default configuration to specified path and exit'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    args = parser.parse_args()

    # Handle save-config option
    if args.save_config:
        save_default_config(args.save_config)
        return 0

    # Require input file for processing
    if not args.input:
        parser.error('Input PDF file is required (unless using --save-config)')

    # Validate input file
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {args.input}")
        return 1

    if not input_path.suffix.lower() == '.pdf':
        print(f"Warning: Input file does not have .pdf extension: {args.input}")

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        output_path = str(input_path.with_suffix('')) + '_marked.txt'

    # Load configuration
    config = load_config(args.config)

    # Process the PDF
    try:
        process_pdf(str(input_path), output_path, config)
        print(f"\nConversion complete: {output_path}")
        return 0
    except Exception as e:
        print(f"Error processing PDF: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
