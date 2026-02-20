import io
from pypdf import PdfReader
from docx import Document

def extract_text_from_pdf(file_bytes):
    """Reads a PDF file from memory bytes."""
    try:
        # Create a PDF reader object from the bytes
        pdf_file = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_file)
        
        text = ""
        # Loop through every page and grab the text
        for page in reader.pages:
            text += page.extract_text() + "\n"
            
        return f"--- START OF PDF CONTENT ---\n{text}\n--- END OF PDF CONTENT ---"
    except Exception as e:
        return f"[Error reading PDF: {e}]"

def extract_text_from_docx(file_bytes):
    """Reads a Word (.docx) file from memory bytes."""
    try:
        # Create a Word document object
        doc_file = io.BytesIO(file_bytes)
        doc = Document(doc_file)
        
        text = ""
        # Loop through every paragraph
        for para in doc.paragraphs:
            text += para.text + "\n"
            
        return f"--- START OF WORD DOC CONTENT ---\n{text}\n--- END OF WORD DOC CONTENT ---"
    except Exception as e:
        return f"[Error reading Word Document: {e}]"