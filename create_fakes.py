import random

def create_form16():
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(r"E:\fake_form16.pdf")
    c.setFont("Helvetica-Bold", 16)
    c.drawString(200, 800, "FORM 16")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(200, 780, "PART B")
    
    c.setFont("Helvetica", 10)
    y = 750
    c.drawString(50, y, "Employer Name: GALAXY TECH PVT LTD")
    c.drawString(300, y, "Employee Name: JOHN DOE")
    y -= 20
    c.drawString(50, y, "Employer TAN: DELG12345E")
    c.drawString(300, y, "Employee PAN: ABCDE1234F")
    
    y -= 40
    c.drawString(50, y, "Salary as per provisions contained in section 17(1): 18,50,000")
    y -= 20
    c.drawString(50, y, "Value of perquisites u/s 17(2): 50,000")
    y -= 20
    c.drawString(50, y, "Gross Salary: 19,00,000")
    y -= 40
    c.drawString(50, y, "Less: Allowances exempt under section 10")
    y -= 20
    c.drawString(50, y, "House Rent Allowance u/s 10(13A): 1,20,000")
    y -= 40
    c.drawString(50, y, "Net Salary: 17,80,000")
    y -= 40
    c.drawString(50, y, "Deductions under section 16")
    y -= 20
    c.drawString(50, y, "Standard deduction u/s 16(ia): 50,000")
    y -= 20
    c.drawString(50, y, "Professional tax u/s 16(iii): 2,500")
    
    y -= 40
    c.drawString(50, y, "Income chargeable under the head Salaries: 17,27,500")
    y -= 40
    c.drawString(50, y, "Chapter VI-A Deductions")
    y -= 20
    c.drawString(50, y, "80C (LIC, PPF): 1,50,000")
    y -= 20
    c.drawString(50, y, "80CCD(1B): 50,000")
    y -= 40
    c.drawString(50, y, "Tax on total income: 2,82,500")
    y -= 20
    c.drawString(50, y, "Total tax deducted at source: 2,82,500")
    
    c.save()

def create_bank():
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(r"E:\fake_bank_statement.pdf")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(200, 800, "HDFC BANK - STATEMENT OF ACCOUNT")
    c.setFont("Helvetica", 10)
    
    c.drawString(50, 750, "Name: JOHN DOE")
    c.drawString(50, 730, "Account No: 50100200300400")
    
    c.drawString(50, 680, "Date       | Description                  | Debit    | Credit   | Balance")
    c.drawString(50, 660, "-------------------------------------------------------------------------")
    c.drawString(50, 640, "01/01/2024 | BY SALARY GALAXY TECH        |          | 115000   | 115000")
    c.drawString(50, 620, "15/03/2024 | SB INT CREDITED              |          | 8500     | 123500")
    c.drawString(50, 600, "20/03/2024 | FD INT 12345                 |          | 15000    | 138500")
    c.drawString(50, 580, "25/03/2024 | TDS DEDUCTED                 | 1500     |          | 137000")
    
    c.save()

if __name__ == "__main__":
    try:
        import reportlab
    except ImportError:
        import os
        os.system("pip install reportlab")
        
    create_form16()
    create_bank()
    print("PDFs created")
