from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()  # loads .env

app = Flask(__name__)
from datetime import datetime

@app.template_filter('format_date')
def format_date(value):
    """Convert a date or datetime to dd:mm:yyyy format for templates."""
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y")
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception:
        return str(value)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'devkey')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///law_office.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
def send_client_email(case, subject, message_body):
    """Send an email to the client if all notification conditions are met."""
    settings = Settings.query.first()
    if not settings:
        print("⚠️ No settings record found")
        return

    # Both lawyer and client must have email notifications enabled
    if not settings.email_notifications_enabled or not case.notify_client:
        print("⚠️ Email notifications disabled for this case or globally")
        return

    sender = settings.lawyer_email
    password = settings.email_password
    receiver = case.client_email

    if not receiver:
        print("⚠️ No client email for this case")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = receiver
        msg["Subject"] = subject
        msg.attach(MIMEText(message_body, "plain"))

        with SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)

        print(f"✅ Email sent to {receiver}")
    except Exception as e:
        print(f"❌ Error sending email: {e}")


db = SQLAlchemy(app)

# -----------------------
# Models
# -----------------------
class Case(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_number = db.Column(db.String(120), unique=True, nullable=False)
    lawyer_name = db.Column(db.String(120))
    client_name = db.Column(db.String(120))
    client_email = db.Column(db.String(120))
    client_mobile = db.Column(db.String(50))
    client_address = db.Column(db.Text)
    opponent_name = db.Column(db.String(120))
    court_name = db.Column(db.String(120))
    case_type = db.Column(db.String(120))
    police_station = db.Column(db.String(120))
    location = db.Column(db.String(200))
    filing_date = db.Column(db.Date)
    status = db.Column(db.String(80))
    description = db.Column(db.Text)
    total_fees = db.Column(db.Float, default=0.0)
    fees_paid = db.Column(db.Float, default=0.0)
    fees_pending = db.Column(db.Float, default=0.0)
    notify_client = db.Column(db.Boolean, default=False)

    hearings = db.relationship('Hearing', backref='case', cascade='all, delete-orphan')

    def recalc_fees(self):
        self.fees_pending = (self.total_fees or 0.0) - (self.fees_paid or 0.0)

class Hearing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False)
    hearing_date = db.Column(db.Date)
    stage = db.Column(db.String(200))
    notes = db.Column(db.Text)
    next_hearing_date = db.Column(db.Date, nullable=True)
    updated_status = db.Column(db.String(80))

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'))
    email_to = db.Column(db.String(120))
    subject = db.Column(db.String(200))
    body = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    case = db.relationship('Case', backref=db.backref('notifications', lazy=True))

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lawyer_name = db.Column(db.String(120))
    lawyer_email = db.Column(db.String(120))
    email_password = db.Column(db.String(255))
    email_notifications_enabled = db.Column(db.Boolean, default=False)

# -----------------------
# Helpers
# -----------------------
def init_db():
    with app.app_context():
        db.create_all()
        # Create default settings if none
        if Settings.query.first() is None:
            s = Settings(
                lawyer_name='Your Name',
                lawyer_email=os.getenv('EMAIL_USER', ''),
                email_password=os.getenv('EMAIL_PASS', ''),
                email_notifications_enabled=False
            )
            db.session.add(s)
            db.session.commit()

# -----------------------
# Routes: Basic
# -----------------------
@app.route('/', methods=['GET'])
def index():
    search_query = request.args.get('search', '').strip().lower()
    status_filter = request.args.get('status', 'All').strip()

    print(f"🔍 Search query: {search_query}, 📂 Status filter: {status_filter}")

    query = Case.query

    # --- Apply search filter ---
    if search_query:
        query = query.filter(
            (db.func.lower(Case.case_number).like(f"%{search_query}%")) |
            (db.func.lower(Case.client_name).like(f"%{search_query}%")) |
            (db.func.lower(Case.lawyer_name).like(f"%{search_query}%"))
        )

    # --- Apply status filter ---
    if status_filter != "All":
        query = query.filter(db.func.lower(Case.status) == status_filter.lower())

    recent_cases = query.order_by(Case.id.desc()).all()

    # Debug print matching cases
    print("✅ Matching cases:", [c.case_number for c in recent_cases])

    # Cards data
    total_cases = Case.query.count()
    active_cases = Case.query.filter(Case.status != 'Closed').count()
    closed_cases = Case.query.filter_by(status='Closed').count()

    upcoming_hearings = Hearing.query.filter(
        Hearing.hearing_date >= datetime.today().date()
    ).order_by(Hearing.hearing_date).limit(10).all()

    return render_template(
        'dashboard.html',
        total_cases=total_cases,
        active_cases=active_cases,
        closed_cases=closed_cases,
        upcoming_hearings=upcoming_hearings,
        recent_cases=recent_cases,
        search_query=request.args.get('search', ''),
        status_filter=status_filter
    )


@app.route('/cases')
def view_cases():
    cases = Case.query.order_by(Case.id.desc()).all()
    return render_template('view_cases.html', cases=cases)

@app.route('/case/add', methods=['GET','POST'])
def add_case():
    if request.method == 'POST':
        data = request.form
        cnum = data.get('case_number').strip()
        if Case.query.filter_by(case_number=cnum).first():
            flash('Case number already exists', 'danger')
            return redirect(url_for('add_case'))

        filing_date = None
        if data.get('filing_date'):
            filing_date = datetime.strptime(data.get('filing_date'), '%Y-%m-%d').date()

        case = Case(
            case_number=cnum,
            lawyer_name=data.get('lawyer_name'),
            client_name=data.get('client_name'),
            client_email=data.get('client_email'),
            client_mobile=data.get('client_mobile'),
            client_address=data.get('client_address'),
            opponent_name=data.get('opponent_name'),
            court_name=data.get('court_name'),
            case_type=data.get('case_type'),
            police_station=data.get('police_station'),
            location=data.get('location'),
            filing_date=filing_date,
            status=data.get('status'),
            description=data.get('description'),
            total_fees=float(data.get('total_fees') or 0),
            fees_paid=float(data.get('fees_paid') or 0),
            notify_client=(data.get('notify_client')=='on')
        )
        case.recalc_fees()
        db.session.add(case)
        db.session.commit()
        flash('Case added', 'success')
        return redirect(url_for('view_cases'))
    return render_template('add_case.html')

@app.route('/case/<int:case_id>')
def case_details(case_id):
    case = Case.query.get_or_404(case_id)
    hearings = Hearing.query.filter_by(case_id=case.id).order_by(Hearing.hearing_date.desc()).all()
    return render_template('case_details.html', case=case, hearings=hearings)

@app.route('/case/<int:case_id>/edit', methods=['GET', 'POST'])
def edit_case(case_id):
    case = Case.query.get_or_404(case_id)
    if request.method == 'POST':
        data = request.form
        # simple validation
        if not data.get('case_number') or not data.get('client_name'):
            flash('Case number and client name are required', 'danger')
            return redirect(url_for('edit_case', case_id=case.id))

        # check duplicate case number (if changed)
        other = Case.query.filter(Case.case_number == data.get('case_number'), Case.id != case.id).first()
        if other:
            flash('Case number already exists', 'danger')
            return redirect(url_for('edit_case', case_id=case.id))

        # update fields
        case.case_number = data.get('case_number').strip()
        case.lawyer_name = data.get('lawyer_name')
        case.client_name = data.get('client_name')
        case.client_email = data.get('client_email')
        case.client_mobile = data.get('client_mobile')
        case.client_address = data.get('client_address')
        case.opponent_name = data.get('opponent_name')
        case.court_name = data.get('court_name')
        case.case_type = data.get('case_type')
        case.police_station = data.get('police_station')
        case.location = data.get('location')
        case.status = data.get('status')
        case.description = data.get('description')
        case.total_fees = float(data.get('total_fees') or 0)
        case.fees_paid = float(data.get('fees_paid') or 0)
        case.notify_client = (data.get('notify_client') == 'on')
        case.recalc_fees()

        db.session.commit()
        # If case status changed, send client notification
        subject = f"Case Status Updated – {case.case_number}"
        message = (
          f"Dear {case.client_name},\n\n"
          f"The status of your case {case.case_number} has been updated.\n"
          f"Current Status: {case.status}\n"
          f"Fees Pending: {case.fees_pending}\n\n"
          f"Regards,\n{case.lawyer_name}"
          )
        send_client_email(case, subject, message)

        flash('Case updated successfully', 'success')
        return redirect(url_for('case_details', case_id=case.id))
    return render_template('edit_case.html', case=case)

@app.route('/case/<int:case_id>/delete', methods=['POST'])
def delete_case(case_id):
    case = Case.query.get_or_404(case_id)
    db.session.delete(case)
    db.session.commit()
    flash('Case deleted successfully', 'success')
    return redirect(url_for('view_cases'))
# -----------------------
# Hearing CRUD
# -----------------------

@app.route('/case/<int:case_id>/hearing/add', methods=['GET', 'POST'])
def add_hearing(case_id):
    case = Case.query.get_or_404(case_id)
    if request.method == 'POST':
        data = request.form
        hearing_date = datetime.strptime(data.get('hearing_date'), '%Y-%m-%d').date() if data.get('hearing_date') else None
        next_hearing_date = datetime.strptime(data.get('next_hearing_date'), '%Y-%m-%d').date() if data.get('next_hearing_date') else None

        h = Hearing(
            case_id=case.id,
            hearing_date=hearing_date,
            stage=data.get('stage'),
            notes=data.get('notes'),
            next_hearing_date=next_hearing_date,
            updated_status=data.get('updated_status')
        )
        db.session.add(h)

        # Update case status if given
        if data.get('updated_status'):
            case.status = data.get('updated_status')

        db.session.commit()

        # ---- Email Notification ----
        subject = f"New Hearing Added – Case {case.case_number}"
        message = (
            f"Dear {case.client_name},\n\n"
            f"A new hearing has been scheduled for your case {case.case_number}.\n"
            f"Hearing Date: {data.get('hearing_date')}\n"
            f"Stage: {data.get('stage')}\n"
            f"Next Hearing Date: {data.get('next_hearing_date')}\n"
            f"Current Case Status: {case.status}\n\n"
            f"Regards,\n{case.lawyer_name}"
        )
        send_client_email(case, subject, message)

        flash('Hearing added successfully', 'success')
        return redirect(url_for('case_details', case_id=case.id))

    # ✅ Always return a response for GET
    return render_template('add_hearing.html', case=case)


@app.route('/hearing/<int:hearing_id>/edit', methods=['GET', 'POST'])
def edit_hearing(hearing_id):
    hearing = Hearing.query.get_or_404(hearing_id)
    case = hearing.case
    if request.method == 'POST':
        data = request.form
        hearing.hearing_date = datetime.strptime(data.get('hearing_date'), '%Y-%m-%d').date()
        hearing.stage = data.get('stage')
        hearing.notes = data.get('notes')
        hearing.next_hearing_date = datetime.strptime(data.get('next_hearing_date'), '%Y-%m-%d').date() if data.get('next_hearing_date') else None
        hearing.updated_status = data.get('updated_status')

        # Update case status automatically if changed
        if data.get('updated_status'):
            case.status = data.get('updated_status')

        db.session.commit()
        flash('Hearing updated successfully', 'success')
        return redirect(url_for('case_details', case_id=case.id))

    return render_template('edit_hearing.html', hearing=hearing, case=case)


@app.route('/hearing/<int:hearing_id>/delete', methods=['POST'])
def delete_hearing(hearing_id):
    hearing = Hearing.query.get_or_404(hearing_id)
    cid = hearing.case_id
    db.session.delete(hearing)
    db.session.commit()
    flash('Hearing deleted successfully', 'success')
    return redirect(url_for('case_details', case_id=cid))
from smtplib import SMTP, SMTPAuthenticationError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# -----------------------
# Lawyer Settings Routes
# -----------------------

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    s = Settings.query.first()
    if not s:
        s = Settings(lawyer_name='', lawyer_email='', email_password='', email_notifications_enabled=False)
        db.session.add(s)
        db.session.commit()

    if request.method == 'POST':
        data = request.form
        s.lawyer_name = data.get('lawyer_name')
        s.lawyer_email = data.get('lawyer_email')
        s.email_password = data.get('email_password')
        s.email_notifications_enabled = (data.get('email_notifications_enabled') == 'on')
        db.session.commit()
        flash('Settings updated successfully', 'success')
        return redirect(url_for('settings'))

    return render_template('settings.html', settings=s)


@app.route('/settings/test-email', methods=['POST'])
def test_email():
    s = Settings.query.first()
    if not s or not s.lawyer_email or not s.email_password:
        flash('Please save valid email credentials before testing.', 'danger')
        return redirect(url_for('settings'))

    try:
        send_test_email(s.lawyer_email, s.email_password)
        flash('Test email sent successfully (check your inbox).', 'success')
    except SMTPAuthenticationError:
        flash('Authentication failed. Check email or app password.', 'danger')
    except Exception as e:
        flash(f'Error sending test email: {e}', 'danger')
    return redirect(url_for('settings'))


def send_test_email(user, password):
    msg = MIMEMultipart()
    msg['From'] = user
    msg['To'] = user
    msg['Subject'] = "Test Email - LOCMS"
    msg.attach(MIMEText("This is a test email from your Law Office Case Management System.", 'plain'))

    with SMTP('smtp.gmail.com', 587) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from smtplib import SMTP
from datetime import datetime

def send_client_email(case, subject, message_body):
    """Send HTML email to client and log the notification in DB."""
    settings = Settings.query.first()
    if not settings:
        print("⚠️ No settings found")
        return

    # Check global + case-level notification switches
    if not settings.email_notifications_enabled or not getattr(case, "notify_client", True):
        print("⚠️ Notifications disabled globally or for this case")
        return

    sender = settings.lawyer_email
    password = settings.email_password
    receiver = case.client_email
    if not receiver:
        print("⚠️ Case has no client email")
        return

    # ----- Build HTML email -----
    html_body = f"""
    <html>
      <body style="font-family:Arial, sans-serif; line-height:1.6;">
        <h3 style="color:#2c3e50;">{subject}</h3>
        <p>{message_body.replace(chr(10), '<br>')}</p>
        <hr>
        <p style="font-size:0.9em;color:#888;">
          Sent by {settings.lawyer_name} – Law Office Case Management System
        </p>
      </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = sender
        msg["To"] = receiver
        msg["Subject"] = subject
        msg.attach(MIMEText(message_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)

        print(f"✅ Email sent to {receiver}")

        # ---- Log the email in Notification table ----
        note = Notification(
            case_id=case.id,
            email_to=receiver,
            subject=subject,
            body=message_body,
            sent_at=datetime.utcnow()
        )
        db.session.add(note)
        db.session.commit()

    except Exception as e:
        print(f"❌ Email send error: {e}")
    
# small route to initialize DB quickly
@app.route('/init-db')
def route_init_db():
    init_db()
    return "DB initialized"

@app.route('/case/<int:case_id>/notifications')
def case_notifications(case_id):
    case = Case.query.get_or_404(case_id)
    notes = Notification.query.filter_by(case_id=case_id).order_by(Notification.sent_at.desc()).all()
    return render_template('notifications.html', case=case, notes=notes)
from openpyxl import Workbook
from io import BytesIO
from flask import send_file

@app.route('/notification/<int:note_id>/resend')
def resend_notification(note_id):
    note = Notification.query.get_or_404(note_id)
    case = note.case
    try:
        # Reuse our existing email sender
        send_client_email(case, note.subject, note.body)
        flash(f"Email re-sent to {note.email_to}", "success")
    except Exception as e:
        flash(f"Error re-sending email: {e}", "danger")
    return redirect(url_for('case_notifications', case_id=case.id))

@app.route('/case/<int:case_id>/notifications/export')
def export_notifications(case_id):
    case = Case.query.get_or_404(case_id)
    notes = Notification.query.filter_by(case_id=case_id).order_by(Notification.sent_at.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Notifications"
    ws.append(["Date Sent", "To", "Subject", "Body"])
    for n in notes:
        ws.append([
            n.sent_at.strftime("%d:%m:%Y %H:%M"),
            n.email_to,
            n.subject,
            n.body
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"Case_{case.case_number}_Notifications.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# -----------------------
# Run
# -----------------------
if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)

