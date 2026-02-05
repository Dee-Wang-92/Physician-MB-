#!/usr/bin/env python3
"""
PDF Text Marker (Claude API Version)

Converts PDF payment schedules to marked-up text using Claude API.
Processes PDF in batches (default 10 pages) and sends to Claude with
a customizable prompt file for tagging instructions.

Usage:
    python pdf_text_marker_claude.py --pdf input.pdf --prompt tagging_prompt.md -o output.txt
    python pdf_text_marker_claude.py --pdf input.pdf --prompt tagging_prompt.md --batch-size 5

Requirements:
    pip install anthropic pymupdf
"""

import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional

# Claude API key - replace ### with your actual key
CLAUDE_API_KEY = "###"

# Try to import required libraries
try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF is required. Install with: pip install pymupdf")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("Error: anthropic is required. Install with: pip install anthropic")
    sys.exit(1)


# =============================================================================
# PDF TEXT EXTRACTION
# =============================================================================

def extract_pages_text(pdf_path: str, start_page: int, end_page: int) -> str:
    """
    Extract text from a range of PDF pages.

    Args:
        pdf_path: Path to PDF file
        start_page: Starting page (1-indexed)
        end_page: Ending page (1-indexed, inclusive)

    Returns:
        Combined text from the specified pages
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    # Adjust end_page if it exceeds total
    end_page = min(end_page, total_pages)

    text_parts = []

    for page_num in range(start_page - 1, end_page):  # fitz uses 0-indexed
        page = doc[page_num]
        text = page.get_text("text")
        text_parts.append(f"--- Page {page_num + 1} ---\n{text}")

    doc.close()

    return "\n\n".join(text_parts)


def get_total_pages(pdf_path: str) -> int:
    """Get total number of pages in a PDF."""
    doc = fitz.open(pdf_path)
    total = len(doc)
    doc.close()
    return total


# =============================================================================
# PROMPT LOADING
# =============================================================================

def load_prompt(prompt_path: str) -> str:
    """Load tagging instructions from a markdown file."""
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()


# =============================================================================
# CLAUDE API INTERACTION
# =============================================================================

def call_claude_api(
    client: anthropic.Anthropic,
    system_prompt: str,
    user_content: str,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 16000
) -> str:
    """
    Call Claude API to tag the text.

    Args:
        client: Anthropic client
        system_prompt: The tagging instructions
        user_content: The PDF text to tag
        model: Claude model to use
        max_tokens: Maximum tokens in response

    Returns:
        Tagged text from Claude
    """
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"Please tag the following PDF content according to the instructions:\n\n{user_content}"
            }
        ]
    )

    # Extract text from response
    return message.content[0].text


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def process_pdf(
    pdf_path: str,
    prompt_path: str,
    output_path: str,
    batch_size: int = 10,
    model: str = "claude-sonnet-4-20250514",
    delay_seconds: float = 1.0
) -> None:
    """
    Process a PDF file using Claude API for tagging.

    Args:
        pdf_path: Path to input PDF
        prompt_path: Path to tagging prompt markdown file
        output_path: Path to output text file
        batch_size: Number of pages to process per API call
        model: Claude model to use
        delay_seconds: Delay between API calls (rate limiting)
    """
    # Validate inputs
    if not Path(pdf_path).exists():
        print(f"Error: PDF file not found: {pdf_path}")
        sys.exit(1)

    if not Path(prompt_path).exists():
        print(f"Error: Prompt file not found: {prompt_path}")
        sys.exit(1)

    if CLAUDE_API_KEY == "###":
        print("Error: Please set your Claude API key in the script (replace ### with your key)")
        sys.exit(1)

    # Initialize Claude client
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    # Load tagging prompt
    print(f"Loading prompt from: {prompt_path}")
    system_prompt = load_prompt(prompt_path)

    # Get PDF info
    total_pages = get_total_pages(pdf_path)
    print(f"PDF: {pdf_path}")
    print(f"Total pages: {total_pages}")
    print(f"Batch size: {batch_size} pages")

    # Calculate batches
    num_batches = (total_pages + batch_size - 1) // batch_size
    print(f"Total batches: {num_batches}")
    print()

    # Process each batch
    all_tagged_text = []

    for batch_num in range(num_batches):
        start_page = batch_num * batch_size + 1
        end_page = min((batch_num + 1) * batch_size, total_pages)

        print(f"Processing batch {batch_num + 1}/{num_batches} (pages {start_page}-{end_page})...")

        # Extract text for this batch
        batch_text = extract_pages_text(pdf_path, start_page, end_page)

        # Call Claude API
        try:
            tagged_text = call_claude_api(
                client=client,
                system_prompt=system_prompt,
                user_content=batch_text,
                model=model
            )
            all_tagged_text.append(tagged_text)
            print(f"  Batch {batch_num + 1} complete ({len(tagged_text)} chars)")

        except anthropic.APIError as e:
            print(f"  API Error on batch {batch_num + 1}: {e}")
            print(f"  Skipping this batch...")
            all_tagged_text.append(f"\n--- BATCH {batch_num + 1} FAILED (pages {start_page}-{end_page}) ---\n")

        # Rate limiting delay (except for last batch)
        if batch_num < num_batches - 1:
            time.sleep(delay_seconds)

    # Combine all tagged text
    print()
    print("Combining all batches...")
    final_text = "\n\n".join(all_tagged_text)

    # Write output
    print(f"Writing output to: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(final_text)

    # Print summary
    print()
    print("=" * 50)
    print("PROCESSING COMPLETE")
    print("=" * 50)
    print(f"Input PDF: {pdf_path}")
    print(f"Prompt file: {prompt_path}")
    print(f"Output file: {output_path}")
    print(f"Total pages processed: {total_pages}")
    print(f"Total batches: {num_batches}")
    print(f"Output size: {len(final_text):,} characters")


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Convert PDF to marked text using Claude API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic usage
    python pdf_text_marker_claude.py --pdf schedule.pdf --prompt tagging_prompt.md -o output.txt

    # With custom batch size (5 pages at a time)
    python pdf_text_marker_claude.py --pdf schedule.pdf --prompt prompt.md -o output.txt --batch-size 5

    # Using a different Claude model
    python pdf_text_marker_claude.py --pdf schedule.pdf --prompt prompt.md -o output.txt --model claude-3-haiku-20240307

Note: Set your Claude API key in the script by replacing ### with your actual key.
        """
    )

    parser.add_argument(
        '--pdf',
        required=True,
        help='Input PDF file path'
    )

    parser.add_argument(
        '--prompt',
        required=True,
        help='Tagging prompt markdown file path'
    )

    parser.add_argument(
        '-o', '--output',
        required=True,
        help='Output text file path'
    )

    parser.add_argument(
        '--batch-size',
        type=int,
        default=10,
        help='Number of pages to process per API call (default: 10)'
    )

    parser.add_argument(
        '--model',
        default='claude-sonnet-4-20250514',
        help='Claude model to use (default: claude-sonnet-4-20250514)'
    )

    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay in seconds between API calls (default: 1.0)'
    )

    args = parser.parse_args()

    process_pdf(
        pdf_path=args.pdf,
        prompt_path=args.prompt,
        output_path=args.output,
        batch_size=args.batch_size,
        model=args.model,
        delay_seconds=args.delay
    )


if __name__ == '__main__':
    main()
