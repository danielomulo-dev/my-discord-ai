import io
import zipfile
from pypdf import PdfReader
from docx import Document

def extract_text_from_pdf(file_bytes):
    """Reads a PDF file."""
    try:
        pdf_file = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return f"--- START OF PDF CONTENT ---\n{text}\n--- END OF PDF CONTENT ---"
    except Exception as e:
        return f"[Error reading PDF: {e}]"

def extract_text_from_docx(file_bytes):
    """Reads a Word file."""
    try:
        doc_file = io.BytesIO(file_bytes)
        doc = Document(doc_file)
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        return f"--- START OF WORD DOC CONTENT ---\n{text}\n--- END OF WORD DOC CONTENT ---"
    except Exception as e:
        return f"[Error reading Word Document: {e}]"

# --- NEW FUNCTION: ZIP READER ---
def extract_code_from_zip(file_bytes):
    """Unzips a file and extracts text from code files."""
    try:
        input_zip = zipfile.ZipFile(io.BytesIO(file_bytes))
        combined_text = "--- START OF ZIP FILE CONTENT ---\n"
        
        # List of file extensions we want to read (Code & Text)
        valid_extensions = ('.py', '.js', '.html', '.css', '.php', '.json', '.txt', '.md', '.java', '.c', '.cpp', '.sql', '.xml', '.yaml', '.yml', '.ts', '.jsx', '.tsx')
        
        file_count = 0
        
        for name in input_zip.namelist():
            # Skip folders and hidden files
            if name.endswith('/') or name.startswith('__MACOSX') or name.startswith('.'):
                continue
            
            # Only read code files
            if name.lower().endswith(valid_extensions):
                try:
                    content = input_zip.read(name).decode('utf-8', errors='ignore')
                    combined_text += f"\n\n--- FILE: {name} ---\n{content}"
                    file_count += 1
                except:
                    combined_text += f"\n\n--- FILE: {name} (Could not decode text) ---"

        combined_text += "\n--- END OF ZIP FILE CONTENT ---"
        
        if file_count == 0:
            return "[Error: No readable code files found in this ZIP. Is it empty or full of images?]"
            
        return combined_text

    except Exception as e:
        return f"[Error reading ZIP file: {e}]"