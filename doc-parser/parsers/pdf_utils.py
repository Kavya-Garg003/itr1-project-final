import pdfplumber
import re

def pdf_to_structured_text(pdf_path: str) -> str:
    """
    Converts a PDF into a structured 'Markdown-ish' text format that preserves 
    table relationships, making it much easier for LLMs to process.
    """
    structured_content = []
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                structured_content.append(f"--- Page {i+1} ---")
                
                # 1. Extract text with layout preservation hints
                text = page.extract_text(x_tolerance=3, y_tolerance=3)
                if text:
                    structured_content.append(text)
                
                # 2. Extract tables and format as Markdown tables
                tables = page.extract_tables()
                if tables:
                    structured_content.append("\n[Tables found on this page]:")
                    for table in tables:
                        if not table or not any(table): 
                            continue
                        
                        # Normalize row lengths
                        max_cols = max(len(row) for row in table if row)
                        
                        # Build Markdown table
                        md_table = []
                        for row_idx, row in enumerate(table):
                            if not row: 
                                continue
                            # Pad row if needed
                            row = list(row) + [""] * (max_cols - len(row))
                            # Clean cells
                            cells = [str(c or "").replace("\n", " ").strip() for c in row]
                            md_table.append("| " + " | ".join(cells) + " |")
                            
                            # Add separator after header
                            if row_idx == 0:
                                md_table.append("| " + " | ".join(["---"] * max_cols) + " |")
                        
                        structured_content.append("\n".join(md_table))
                        structured_content.append("") # Spacer
                        
        return "\n\n".join(structured_content)
    except Exception as e:
        print(f"Error in pdf_to_structured_text: {e}")
        return ""
