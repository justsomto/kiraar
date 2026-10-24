# ==========================================
# STANDARD IMPORTS
# ==========================================
import os
import secrets
import datetime
import json
import requests
import uuid
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlencode

# ==========================================
# FLASK & SECURITY IMPORTS
# ==========================================
from flask import render_template, url_for, request, flash, redirect, session, jsonify, current_app
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ==========================================
# KIRAAR SPECIFIC IMPORTS
# ==========================================
from pkg import app, csrf
from pkg.forms import LoginForm, ClientSignupForm, ProfessionalSignupForm


# ==========================================
# HELPER FUNCTIONS (Images & Emails)
# These are placed here so you can easily use them in your routes below!
# ==========================================

def clear_professional_session():
    session.pop('professional_id', None)
    session.pop('professional_name', None)
    session.pop('has_dual_account', None)


@app.before_request
def enforce_professional_account_status():
    if 'professional_id' not in session:
        return

    professional = Professional.query.get(session['professional_id'])
    if not professional:
        clear_professional_session()
        return

    if professional.account_status == 'suspended':
        clear_professional_session()

        # Dual-account rule: if a client account exists under the same
        # email, the suspended professional's live session is force-switched
        # to that client account (rather than being logged out entirely) so
        # they can keep using the platform as a client while locked out of
        # professional features.
        client = User.query.filter_by(email=professional.email).first()
        if client:
            session['user_id'] = client.user_id
            session['user_name'] = f"{client.first_name} {client.last_name}"
            session['user_email'] = client.email
            session['has_dual_account'] = True
            # Mark that the pro account is suspended so we can hide the
            # "Switch to Pro" button in templates — they still have a client
            # account, but the toggle must be disabled.
            session['pro_suspended'] = True
            flash('Your professional account has been suspended. You have been switched to your client account.', 'error')
            if request.endpoint not in {'login', 'logout'}:
                return redirect(url_for('results'))
        else:
            flash('Your professional account has been suspended. Please contact Kiraar support.', 'error')
            if request.endpoint not in {'login', 'logout'}:
                return redirect(url_for('login'))


# 1. IMAGE UPLOAD HELPER
# We only want users to upload these specific image types, no malicious scripts!
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

def allowed_file(filename):
    # This checks if the file has a dot (.) and if the text after the dot is in our ALLOWED_EXTENSIONS list.
    if '.' in filename:
        # Split the filename by the dot, get the last part (the extension), and make it lowercase
        extension = filename.rsplit('.', 1)[1].lower()
        if extension in ALLOWED_EXTENSIONS:
            return True
    return False

def save_secure_image(file_obj):
    # Step 1: Make sure a file was actually uploaded
    if not file_obj or file_obj.filename == '':
        return None
        
    # Step 2: Make sure it's a safe image type (like .jpg or .png)
    if not allowed_file(file_obj.filename):
        return None
        
    # Step 3: Use Werkzeug's secure_filename to strip out bad characters from the original name
    secured_name = secure_filename(file_obj.filename)
    
    # Step 4: Extract the file extension (e.g., "jpg")
    extension = secured_name.rsplit('.', 1)[1].lower()
    
    # Step 5: Generate a completely random string (UUID) for the new filename so nobody can guess it
    random_string = uuid.uuid4().hex
    new_filename = f"{random_string}.{extension}"
    
    # Step 6: Define where the file should be saved (static/uploads folder)
    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
    
    # Create the folder if it doesn't exist yet
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
        
    # Step 7: Save the file to the hard drive
    final_path = os.path.join(upload_folder, new_filename)
    file_obj.save(final_path)
    
    # Return just the filename so we can save it in the database
    return new_filename


# 2. EMAIL SENDER HELPER (ASYNCHRONOUS BACKGROUND WORKER)
def _async_send_email(app_obj, to_email, subject, html_body):
    """Sends the email in a separate background thread so page loads stay lightning fast."""
    with app_obj.app_context():
        try:
            sender = app_obj.config.get('MAIL_DEFAULT_SENDER')
            password = app_obj.config.get('MAIL_PASSWORD')
            server_address = app_obj.config.get('MAIL_SERVER')
            port = app_obj.config.get('MAIL_PORT')
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = sender
            msg['To'] = to_email
            
            html_part = MIMEText(html_body, 'html')
            msg.attach(html_part)
            
            server = smtplib.SMTP(server_address, port, timeout=10)
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, to_email, msg.as_string())
            server.quit()
        except Exception as e:
            app_obj.logger.error(f"Async email error for {to_email}: {e}")

def send_email_via_smtp(to_email, subject, html_body):
    """Fires the email in a background thread and returns instantly (0ms delay for user)."""
    try:
        app_obj = current_app._get_current_object()
        t = threading.Thread(target=_async_send_email, args=(app_obj, to_email, subject, html_body), daemon=True)
        t.start()
    except Exception as e:
        print(f"Failed to start async email thread: {e}")

def send_welcome_email(to_email, first_name):
    # Render the welcome HTML template with the user's name
    html_body = render_template('emails/welcome.html', first_name=first_name)
    # Pass it to our helper function to send!
    send_email_via_smtp(to_email, "Welcome to Kiraar!", html_body)


def send_new_booking_email_to_professional(pro_email, pro_name, client_name, service_name, scheduled_date, address, booking_price, booking_id):
    """Notify the professional immediately when a client places a new booking."""
    try:
        html_body = render_template(
            'emails/booking_request_professional.html',
            pro_name=pro_name,
            client_name=client_name,
            service_name=service_name,
            scheduled_date=scheduled_date,
            address=address,
            booking_price=booking_price,
            booking_id=booking_id
        )
        send_email_via_smtp(pro_email, f"New Booking Request from {client_name} — Kiraar", html_body)
    except Exception as e:
        print(f"Failed to send pro booking email: {e}")


def send_new_booking_email_to_client(client_email, client_name, pro_name, business_name, service_name, scheduled_date, address, booking_price, booking_id):
    """Confirm to the client that their booking request was placed successfully."""
    try:
        html_body = render_template(
            'emails/booking_confirmation_client.html',
            client_name=client_name,
            pro_name=pro_name,
            business_name=business_name,
            service_name=service_name,
            scheduled_date=scheduled_date,
            address=address,
            booking_price=booking_price,
            booking_id=booking_id
        )
        send_email_via_smtp(client_email, f"Booking Request Sent to {pro_name} — Kiraar", html_body)
    except Exception as e:
        print(f"Failed to send client booking email: {e}")


def send_password_reset_email(to_email, first_name, reset_url):
    """Send a password reset link to the user."""
    try:
        html_body = render_template('emails/password_reset.html', first_name=first_name, reset_url=reset_url)
        send_email_via_smtp(to_email, "Reset Your Kiraar Password", html_body)
    except Exception as e:
        print(f"Failed to send password reset email: {e}")


def send_profile_completion_nudge(to_email, first_name):
    """Email sent to a new professional who signed up via Google reminding them to complete their profile."""
    try:
        html_body = render_template('emails/profile_completion_nudge.html', first_name=first_name)
        send_email_via_smtp(to_email, "Complete Your Kiraar Professional Profile", html_body)
    except Exception as e:
        print(f"Failed to send profile completion nudge email: {e}")


def send_job_completion_email(client_email, client_name, professional_name, booking_id, professional_id):
    """Send email to client when professional marks a job as completed."""
    review_url = f"http://127.0.0.1:5057/professional/{professional_id}/profile/"
    complaint_url = f"http://127.0.0.1:5057/client/complaint/{booking_id}/"
    try:
        html_body = render_template(
            'emails/job_completed.html',
            client_name=client_name,
            professional_name=professional_name,
            booking_id=booking_id,
            review_url=review_url,
            complaint_url=complaint_url
        )
        send_email_via_smtp(client_email, f"Your booking #{booking_id} has been completed!", html_body)
    except Exception as e:
        print(f"Failed to send job completion email: {e}")

def send_complaint_received_email(client_email, client_name, booking_id, subject):
    """Notify client that their complaint has been received and is under review."""
    try:
        html_body = render_template('emails/complaint_received.html', client_name=client_name, booking_id=booking_id, subject=subject)
        send_email_via_smtp(client_email, f"Complaint Received - Booking #{booking_id}", html_body)
    except Exception as e:
        print(f"Failed to send complaint received email: {e}")

def send_payout_email(professional_email, professional_name, amount, booking_id, bank_name, account_number, reference):
    """Notify artisan when a payment has been transferred to their bank account."""
    try:
        html_body = render_template(
            'emails/payout_received.html',
            professional_name=professional_name,
            amount=amount,
            booking_id=booking_id,
            bank_name=bank_name,
            account_number=account_number,
            reference=reference
        )
        send_email_via_smtp(
            professional_email,
            f"Payment of ₦{amount:,.2f} Sent to Your Bank! - Booking #{booking_id}",
            html_body
        )
    except Exception as e:
        print(f"Failed to send payout email: {e}")

def send_client_payment_receipt_email(client_email, client_name, amount, booking_id, professional_name, business_name, scheduled_date, address, reference):
    """Send an official payment receipt email to client after paying for a booking."""
    try:
        html_body = render_template(
            'emails/payment_receipt.html',
            client_name=client_name,
            amount=amount,
            booking_id=booking_id,
            professional_name=professional_name,
            business_name=business_name,
            scheduled_date=scheduled_date,
            address=address,
            reference=reference
        )
        send_email_via_smtp(
            client_email,
            f"Payment Receipt - Booking #{booking_id} (₦{amount:,.2f})",
            html_body
        )
    except Exception as e:
        print(f"Failed to send payment receipt email: {e}")

from pkg.models import db, User, Professional, ServiceCategory, ProfessionalService, Booking, Review, Product, Complaint, Payout

@app.context_processor
def inject_unpaid_count():
    unpaid_count = 0
    if 'user_id' in session:
        unpaid_count = Booking.query.filter_by(user_id=session['user_id'], payment_status='unpaid').count()
    return dict(unpaid_bookings_count=unpaid_count)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about/')
def about():
    return render_template('about.html')

@app.route('/terms/')
def terms():
    return render_template('terms.html')

@app.route('/privacy/')
def privacy():
    return render_template('privacy.html')

@app.route('/escrow-policy/')
def escrow_policy():
    return render_template('escrow_policy.html')

def send_contact_inquiry_emails(name, sender_email, phone, subject, message_content):
    admin_email = current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config.get('MAIL_USERNAME', 'franklinsomto7@gmail.com')
    
    try:
        admin_html = render_template(
            'emails/contact_admin_notification.html',
            name=name,
            sender_email=sender_email,
            phone=phone,
            subject=subject,
            message_content=message_content
        )
        send_email_via_smtp(admin_email, f"[Kiraar Support] {subject} from {name}", admin_html)
    except Exception as e:
        print(f"Error sending admin contact email: {e}")

    try:
        user_html = render_template(
            'emails/contact_user_confirmation.html',
            name=name,
            subject=subject,
            message_content=message_content
        )
        send_email_via_smtp(sender_email, "We have received your message - Kiraar Support", user_html)
    except Exception as e:
        print(f"Error sending user contact confirmation email: {e}")

@app.route('/contact/', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        subject = request.form.get('subject', 'General Inquiry').strip()
        message = request.form.get('message', '').strip()

        if not username or not email or not message:
            flash('Please fill in your name, email, and message.', 'error')
            return render_template('contact.html')

        try:
            send_contact_inquiry_emails(username, email, phone, subject, message)
            flash(f'Thank you, {username}! Your message has been sent successfully. Our support team will get back to you shortly.', 'success')
        except Exception as e:
            app.logger.error(f"Error sending contact email: {e}")
            flash('Your message has been received! Our support team will contact you soon.', 'success')

        return redirect(url_for('contact'))

    return render_template('contact.html')


# ── Google OAuth Routes ────────────────────────────────────────────────────
@app.route('/auth/google/<role>/')
def google_auth(role):
    if role not in ('client', 'pro'):
        role = 'client'

    google_client_id = app.config.get('GOOGLE_CLIENT_ID') or os.environ.get('GOOGLE_CLIENT_ID')
    if not google_client_id:
        from dotenv import load_dotenv
        load_dotenv(override=True)
        google_client_id = os.environ.get('GOOGLE_CLIENT_ID')
        app.config['GOOGLE_CLIENT_ID'] = google_client_id
        app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')

    if not google_client_id:
        flash('Google Sign-In is currently in setup mode. Please enter your details below to sign up.', 'info')
        return redirect(url_for('signup', tab=role))

    redirect_uri = url_for('google_callback', _external=True)
    if 'localhost:5057' in redirect_uri:
        redirect_uri = redirect_uri.replace('localhost:5057', '127.0.0.1:5057')
    elif redirect_uri.startswith('http://') and not ('127.0.0.1' in redirect_uri or 'localhost' in redirect_uri):
        redirect_uri = redirect_uri.replace('http://', 'https://', 1)

    state = json.dumps({'role': role})
    params = {
        'client_id': google_client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'access_type': 'online',
        'prompt': 'select_account'
    }
    google_auth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)
    return redirect(google_auth_url)


@app.route('/auth/google/callback/')
def google_callback():
    code = request.args.get('code')
    state = request.args.get('state', '{}')

    try:
        state_data = json.loads(state)
        role = state_data.get('role', 'client')
    except Exception:
        role = 'client'

    if not code:
        flash('Google sign-in was cancelled.', 'error')
        return redirect(url_for('signup', tab=role))

    google_client_id = app.config.get('GOOGLE_CLIENT_ID') or os.environ.get('GOOGLE_CLIENT_ID')
    google_client_secret = app.config.get('GOOGLE_CLIENT_SECRET') or os.environ.get('GOOGLE_CLIENT_SECRET')
    if not (google_client_id and google_client_secret):
        from dotenv import load_dotenv
        load_dotenv(override=True)
        google_client_id = os.environ.get('GOOGLE_CLIENT_ID')
        google_client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')

    redirect_uri = url_for('google_callback', _external=True)
    if 'localhost:5057' in redirect_uri:
        redirect_uri = redirect_uri.replace('localhost:5057', '127.0.0.1:5057')
    elif redirect_uri.startswith('http://') and not ('127.0.0.1' in redirect_uri or 'localhost' in redirect_uri):
        redirect_uri = redirect_uri.replace('http://', 'https://', 1)

    token_url = 'https://oauth2.googleapis.com/token'
    token_data = {
        'code': code,
        'client_id': google_client_id,
        'client_secret': google_client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }

    try:
        r = requests.post(token_url, data=token_data, timeout=10)
        tokens = r.json()
        access_token = tokens.get('access_token')
        if not access_token:
            flash('Failed to authenticate with Google. Please try signing up with email.', 'error')
            return redirect(url_for('signup', tab=role))

        user_info_resp = requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10
        )
        user_info = user_info_resp.json()
        email = user_info.get('email', '').lower()
        first_name = user_info.get('given_name') or user_info.get('name', 'User').split()[0]
        name_parts = user_info.get('name', '').split()
        last_name = user_info.get('family_name') or (name_parts[-1] if len(name_parts) > 1 else 'Member')

        if not email:
            flash('Google account did not provide an email address.', 'error')
            return redirect(url_for('signup', tab=role))

        # Handle Client Google Signup / Login
        if role == 'client':
            existing_user = User.query.filter_by(email=email).first()
            if not existing_user:
                random_pw = generate_password_hash(os.urandom(16).hex())
                new_user = User(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    password=random_pw,
                    phone_number=''
                )
                db.session.add(new_user)
                db.session.commit()
                existing_user = new_user
                try:
                    send_welcome_email(existing_user.email, existing_user.first_name)
                except Exception as e:
                    print(f"Error sending welcome email: {e}")

            session['user_id'] = existing_user.user_id
            session['user_name'] = f"{existing_user.first_name} {existing_user.last_name}"
            session['user_email'] = existing_user.email

            existing_pro = Professional.query.filter_by(email=email).first()
            if existing_pro:
                session['has_dual_account'] = True
                if existing_pro.account_status == 'suspended':
                    session['pro_suspended'] = True

            flash('Successfully signed in with Google!', 'success')
            return redirect(url_for('results'))

        # Handle Professional Google Signup / Login
        elif role == 'pro':
            existing_pro = Professional.query.filter_by(email=email).first()
            if not existing_pro:
                random_pw = generate_password_hash(os.urandom(16).hex())
                new_pro = Professional(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    password=random_pw,
                    phone_number='',
                    business_name=f"{first_name}'s Services",
                    bio='',
                    account_status='pending'
                )
                db.session.add(new_pro)
                db.session.commit()
                existing_pro = new_pro
                try:
                    send_welcome_email(existing_pro.email, existing_pro.first_name)
                except Exception as e:
                    print(f"Error sending welcome email: {e}")
                try:
                    send_profile_completion_nudge(existing_pro.email, existing_pro.first_name)
                except Exception as e:
                    print(f"Error sending profile completion nudge: {e}")

            if existing_pro.account_status == 'suspended':
                flash('Your professional account has been suspended. Please contact Kiraar support.', 'error')
                return redirect(url_for('login'))

            session['professional_id'] = existing_pro.professional_id
            session['professional_name'] = f"{existing_pro.first_name} {existing_pro.last_name}"

            existing_client = User.query.filter_by(email=email).first()
            if existing_client:
                session['has_dual_account'] = True

            flash('Successfully signed in with Google!', 'success')
            return redirect(url_for('find_jobs'))

    except Exception as e:
        app.logger.error(f"Google OAuth callback error: {e}")
        flash('An error occurred during Google sign-in. Please use email registration.', 'error')
        return redirect(url_for('signup', tab=role))

@app.route('/find-jobs/')
def find_jobs():
    if 'professional_id' not in session:
        if 'user_id' in session:
            # If they are logged in as a client, they belong on the results page
            client = User.query.get(session['user_id'])
            if client:
                pro = Professional.query.filter_by(email=client.email).first()
                if pro and pro.account_status == 'suspended':
                    flash('Your professional account has been suspended. You can continue using your client account.', 'error')
                    return redirect(url_for('results'))
            flash('This page is only for professionals.', 'info')
            return redirect(url_for('results'))
        flash('Please log in to access this page.', 'error')
        return redirect(url_for('login'))

    # Extra safety check: if a professional is in session but their account
    # has been suspended, block them immediately and switch to client if possible.
    if 'professional_id' in session:
        _pro_check = Professional.query.get(session['professional_id'])
        if _pro_check and _pro_check.account_status == 'suspended':
            clear_professional_session()
            _client = User.query.filter_by(email=_pro_check.email).first()
            if _client:
                session['user_id'] = _client.user_id
                session['user_name'] = f"{_client.first_name} {_client.last_name}"
                session['user_email'] = _client.email
                session['has_dual_account'] = True
                session['pro_suspended'] = True
                flash('Your professional account has been suspended. You have been switched to your client account.', 'error')
                return redirect(url_for('results'))
            else:
                session.clear()
                flash('Your professional account has been suspended. Please contact Kiraar support.', 'error')
                return redirect(url_for('login'))

    professional = None
    years_on_kiraar = 0
    prof_service_names = []
    if 'professional_id' in session:
        professional = Professional.query.get(session['professional_id'])
        if professional and professional.date_joined:
            delta = datetime.datetime.now() - professional.date_joined.replace(tzinfo=None)
            years_on_kiraar = max(0, delta.days // 365)
        # Get the names of all services this professional offers
        if professional:
            for ps in ProfessionalService.query.filter_by(professional_id=professional.professional_id).all():
                cat = ServiceCategory.query.get(ps.service_category_id)
                if cat:
                    prof_service_names.append(cat.service_category_name)

    # Get real bookings for this professional
    bookings = []
    wallet_balance = 0.0
    todays_earnings = 0.0
    completed_jobs = 0
    average_rating = 0.0

    if professional:
        bookings = Booking.query.filter_by(professional_id=professional.professional_id).order_by(Booking.booking_id.desc()).all()
        average_rating = float(professional.average_rating or 0.0)
        
        today = datetime.datetime.now().date()
        for b in bookings:
            if b.job_status == 'completed':
                completed_jobs += 1
                if b.payment_status == 'paid':
                    wallet_balance += float(b.booking_price or 0.0)
                    if b.completion_date and b.completion_date.date() == today:
                        todays_earnings += float(b.booking_price or 0.0)

    cometchat_app_id = app.config['COMETCHAT_APP_ID']
    cometchat_region = app.config['COMETCHAT_REGION']

    return render_template(
        'find_jobs.html', 
        professional=professional, 
        years_on_kiraar=years_on_kiraar, 
        prof_service_names=prof_service_names, 
        bookings=bookings, 
        cometchat_app_id=cometchat_app_id, 
        cometchat_region=cometchat_region,
        wallet_balance=wallet_balance,
        todays_earnings=todays_earnings,
        completed_jobs=completed_jobs,
        average_rating=average_rating
    )

@app.route('/professional/dashboard/')
def professional_dashboard():
    if 'professional_id' not in session:
        if 'user_id' in session:
            flash('This dashboard is for professionals.', 'info')
            return redirect(url_for('results'))
        flash('Please log in to access your dashboard.', 'error')
        return redirect(url_for('login'))

    pro_check = Professional.query.get(session['professional_id'])
    if not pro_check or pro_check.account_status == 'suspended':
        flash('Your professional account has been suspended. Please contact Kiraar support.', 'error')
        return redirect(url_for('login'))

    professional = pro_check
    delta = datetime.datetime.now() - (professional.date_joined.replace(tzinfo=None) if professional.date_joined else datetime.datetime.now())
    years_on_kiraar = max(0, delta.days // 365)

    prof_service_names = []
    for ps in ProfessionalService.query.filter_by(professional_id=professional.professional_id).all():
        cat = ServiceCategory.query.get(ps.service_category_id)
        if cat:
            prof_service_names.append(cat.service_category_name)

    bookings = Booking.query.filter_by(professional_id=professional.professional_id).order_by(Booking.booking_id.desc()).all()
    wallet_balance = 0.0
    todays_earnings = 0.0
    total_lifetime_earnings = 0.0
    completed_jobs = 0
    in_progress_jobs = 0
    pending_jobs = 0

    today = datetime.datetime.now().date()
    for b in bookings:
        if b.job_status == 'completed':
            completed_jobs += 1
            if b.payment_status == 'paid':
                earnings_amt = float(b.booking_price or 0.0)
                wallet_balance += earnings_amt
                total_lifetime_earnings += earnings_amt
                if b.completion_date and b.completion_date.date() == today:
                    todays_earnings += earnings_amt
        elif b.job_status == 'in-progress':
            in_progress_jobs += 1
        elif b.job_status == 'pending':
            pending_jobs += 1

    average_rating = float(professional.average_rating or 0.0)
    reviews_count = Review.query.filter_by(professional_id=professional.professional_id).count()

    return render_template(
        'professional_dashboard.html',
        professional=professional,
        years_on_kiraar=years_on_kiraar,
        prof_service_names=prof_service_names,
        bookings=bookings,
        wallet_balance=wallet_balance,
        todays_earnings=todays_earnings,
        total_lifetime_earnings=total_lifetime_earnings,
        completed_jobs=completed_jobs,
        in_progress_jobs=in_progress_jobs,
        pending_jobs=pending_jobs,
        average_rating=average_rating,
        reviews_count=reviews_count
    )

@app.route('/login/', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        professional = Professional.query.filter_by(email=form.email.data.lower()).first()

        if user and check_password_hash(user.password, form.password.data):
            session['user_id'] = user.user_id
            session['user_name'] = f"{user.first_name} {user.last_name}"
            session['user_email'] = user.email
            # Check if this same email also has a professional account
            if professional:
                session['has_dual_account'] = True
                # If that professional account is suspended, mark it so the
                # "Switch to Pro" button is hidden — they can still use the
                # platform as a client, but cannot switch to professional mode.
                if professional.account_status == 'suspended':
                    session['pro_suspended'] = True
            flash('Login successful!', 'success')
            return redirect(url_for('results'))

        if professional and check_password_hash(professional.password, form.password.data):
            if professional.account_status == 'suspended':
                flash('Your professional account has been suspended. Please contact Kiraar support.', 'error')
                return redirect(url_for('login'))

            session['professional_id'] = professional.professional_id
            session['professional_name'] = f"{professional.first_name} {professional.last_name}"
            # Check if this same email also has a client account
            if user:
                session['has_dual_account'] = True
            flash('Login successful!', 'success')
            return redirect(url_for('find_jobs'))

        flash('Invalid email or password.', 'error')
    return render_template('login.html', form=form)


@app.route('/switch-role/')
def switch_role():
    # This route lets a dual-account user switch between their client and professional dashboards.
    if 'user_id' in session:
        # They are currently logged in as a client, switch them to professional
        email = User.query.get(session['user_id']).email
        professional = Professional.query.filter_by(email=email).first()
        if professional:
            if professional.account_status == 'suspended':
                flash('Your professional account has been suspended. Please contact Kiraar support.', 'error')
                return redirect(url_for('results'))

            session.pop('user_id', None)
            session.pop('user_name', None)
            session['professional_id'] = professional.professional_id
            session['professional_name'] = f"{professional.first_name} {professional.last_name}"
            session['has_dual_account'] = True
            flash('Switched to your Professional account.', 'success')
            return redirect(url_for('find_jobs'))

    elif 'professional_id' in session:
        # They are currently logged in as a professional, switch them to client
        email = Professional.query.get(session['professional_id']).email
        user = User.query.filter_by(email=email).first()
        if user:
            session.pop('professional_id', None)
            session.pop('professional_name', None)
            session['user_id'] = user.user_id
            session['user_name'] = f"{user.first_name} {user.last_name}"
            session['user_email'] = user.email
            session['has_dual_account'] = True
            flash('Switched to your Client account.', 'success')
            return redirect(url_for('results'))

    # If something goes wrong, just log them out
    flash('Could not switch accounts. Please log in again.', 'error')
    return redirect(url_for('logout'))

@app.route('/results/')
def results():
    search_query = request.args.get('search', '').strip()
    category_query = request.args.get('category', '').strip()

    # Show both verified and pending professionals, but exclude suspended accounts
    professionals = Professional.query.filter(Professional.account_status != 'suspended').all()
    service_categories = ServiceCategory.query.all()

    # Build a dict mapping professional_id -> list of trade names
    prof_trades = {}
    for prof in professionals:
        services = ProfessionalService.query.filter_by(professional_id=prof.professional_id).all()
        trades = []
        for svc in services:
            cat = ServiceCategory.query.get(svc.service_category_id)
            if cat:
                trades.append(cat.service_category_name)
        prof_trades[prof.professional_id] = trades

    cometchat_app_id = app.config.get('COMETCHAT_APP_ID', '')
    cometchat_region = app.config.get('COMETCHAT_REGION', '')

    return render_template(
        'results.html',
        professionals=professionals,
        service_categories=service_categories,
        prof_trades=prof_trades,
        cometchat_app_id=cometchat_app_id,
        cometchat_region=cometchat_region,
        search_query=search_query,
        category_query=category_query
    )


@app.route('/client/edit/', methods=['GET', 'POST'])
def edit_client():
    if 'user_id' not in session:
        flash('Please log in to edit your profile.', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.get(user_id)

    if user is None:
        flash('User profile not found.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        new_first_name = request.form.get('first_name', '').strip()
        new_last_name = request.form.get('last_name', '').strip()
        new_email = request.form.get('email', '').strip().lower()
        new_phone_number = request.form.get('phone_number', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        # If the email changed, make sure no one else already has it
        if new_email != user.email:
            existing_user = User.query.filter_by(email=new_email).first()
            if existing_user and existing_user.user_id != user.user_id:
                flash('That email is already in use by another account.', 'error')
                return render_template('edit_client.html', user=user)

        if new_password or confirm_password:
            if new_password != confirm_password:
                flash('New password and confirmation do not match.', 'error')
                return render_template('edit_client.html', user=user)
            user.password = generate_password_hash(new_password)

        user.first_name = new_first_name
        user.last_name = new_last_name
        user.email = new_email
        user.phone_number = new_phone_number

        db.session.commit()
        session['user_name'] = f"{user.first_name} {user.last_name}"
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('edit_client'))

    return render_template('edit_client.html', user=user)



@app.route('/professional/edit/', methods=['GET', 'POST'])
def edit_professional():
    if 'professional_id' not in session:
        flash('Please log in as a professional to edit your profile.', 'error')
        return redirect(url_for('login'))

    professional_id = session['professional_id']
    professional = Professional.query.get(professional_id)

    if professional is None:
        flash('Professional profile not found.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        professional.first_name = request.form.get('first_name', '').strip()
        professional.last_name = request.form.get('last_name', '').strip()
        professional.business_name = request.form.get('business_name', '').strip()
        professional.phone_number = request.form.get('phone_number', '').strip()
        professional.bio = request.form.get('bio', '').strip()
        professional.business_type = request.form.get('business_type', '').strip()
        professional.location = request.form.get('location', '').strip()
        professional.status = request.form.get('status', '').strip()
        professional.show_first_name = 'show_first_name' in request.form
        professional.show_last_name = 'show_last_name' in request.form
        professional.show_business_name = 'show_business_name' in request.form

        # Bank details are NEVER set directly here anymore — they must go through
        # create_or_update_recipient() so recipient_code is always kept in sync
        # with a successful Paystack transfer-recipient call.
        new_bank_code = request.form.get('bank_code', '').strip()
        new_account_number = request.form.get('account_number', '').strip()
        new_account_name = request.form.get('account_name', '').strip()
        new_bank_name = request.form.get('bank_name', '').strip()

        bank_changed = bool(new_account_number) and (
            new_account_number != (professional.account_number or '') or
            new_bank_code != (professional.bank_code or '')
        )

        if bank_changed:
            success, result = create_or_update_recipient(
                professional, new_bank_code, new_bank_name, new_account_number, new_account_name
            )
            if not success:
                db.session.commit()  # save the non-bank fields already set above
                flash(f'Profile updated, but bank details were not saved: {result}', 'error')
                return redirect(url_for('edit_professional'))


        # Update selected services
        selected_service_ids = request.form.getlist('services')
        if selected_service_ids:
            # Get current services for this professional
            current_services = ProfessionalService.query.filter_by(professional_id=professional.professional_id).all()
            current_service_cat_ids = set(ps.service_category_id for ps in current_services)
            new_service_cat_ids = set(int(svc_id) for svc_id in selected_service_ids)

            # Find services to add (in new list but not in current)
            to_add_ids = new_service_cat_ids - current_service_cat_ids

            # Find services to remove (in current but not in new list)
            to_remove_ids = current_service_cat_ids - new_service_cat_ids

            # Remove services that are NOT referenced by any booking
            for ps in current_services:
                if ps.service_category_id in to_remove_ids:
                    # Check if this service is used in any booking
                    booking_count = Booking.query.filter_by(professional_service_id=ps.professional_service_id).count()
                    if booking_count == 0:
                        db.session.delete(ps)
                    # If it has bookings, keep it (can't delete due to foreign key)

            # Add new services
            for svc_cat_id in to_add_ids:
                ps = ProfessionalService(
                    professional_id=professional.professional_id,
                    service_category_id=svc_cat_id,
                    rate=0.0  # Default rate, can be updated later
                )
                db.session.add(ps)

        if 'profile_picture' in request.files and request.files['profile_picture'].filename:
            saved_filename = save_secure_image(request.files['profile_picture'])
            if saved_filename:
                professional.profile_picture = f'/static/uploads/{saved_filename}'
            else:
                flash('Invalid image format for profile picture. Allowed types: PNG, JPG, JPEG, WEBP, GIF.', 'error')

        db.session.commit()
        session['professional_name'] = f"{professional.first_name} {professional.last_name}"
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('edit_professional'))

    # Get all service categories and which ones this professional offers
    service_categories = ServiceCategory.query.all()
    prof_services = ProfessionalService.query.filter_by(professional_id=professional.professional_id).all()
    prof_service_ids = [ps.service_category_id for ps in prof_services]

    # Calculate years on Kiraar
    if professional.date_joined:
        delta = datetime.datetime.now() - professional.date_joined.replace(tzinfo=None)
        years_on_kiraar = max(0, delta.days // 365)
    else:
        years_on_kiraar = 0

    products = Product.query.filter_by(professional_id=professional_id).all()
    return render_template('edit_professional.html', professional=professional, service_categories=service_categories, prof_service_ids=prof_service_ids, years_on_kiraar=years_on_kiraar, products=products)

@app.route('/logout/')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


# ── Forgot Password ─────────────────────────────────────────────────────────
import hmac, hashlib, time, base64

def _make_reset_token(user_id, role, email):
    """Generate a short-lived signed token: base64(user_id|role|timestamp|hmac)"""
    ts = int(time.time())
    payload = f"{user_id}|{role}|{email}|{ts}"
    sig = hmac.new(
        current_app.config['SECRET_KEY'].encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    raw = f"{payload}|{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()

def _verify_reset_token(token, max_age=1800):
    """Return (user_id, role, email) if token is valid and not expired, else None."""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split('|')
        if len(parts) != 5:
            return None
        user_id, role, email, ts, sig = parts
        ts = int(ts)
        if time.time() - ts > max_age:
            return None
        payload = f"{user_id}|{role}|{email}|{ts}"
        expected = hmac.new(
            current_app.config['SECRET_KEY'].encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        return user_id, role, email
    except Exception:
        return None

@app.route('/forgot-password/', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email:
            flash('Please enter your email address.', 'error')
            return render_template('forgot_password.html')

        user = User.query.filter_by(email=email).first()
        pro  = Professional.query.filter_by(email=email).first()

        if user:
            token = _make_reset_token(user.user_id, 'client', email)
            reset_url = url_for('reset_password', token=token, _external=True)
            try:
                send_password_reset_email(email, user.first_name, reset_url)
            except Exception as e:
                print(f"Error sending reset email: {e}")
        elif pro:
            token = _make_reset_token(pro.professional_id, 'pro', email)
            reset_url = url_for('reset_password', token=token, _external=True)
            try:
                send_password_reset_email(email, pro.first_name, reset_url)
            except Exception as e:
                print(f"Error sending reset email: {e}")

        # Always show same message (security — don't reveal if email exists)
        flash('If an account with that email exists, a password reset link has been sent. Check your inbox.', 'info')
        return redirect(url_for('forgot_password'))

    return render_template('forgot_password.html')


@app.route('/reset-password/<token>/', methods=['GET', 'POST'])
def reset_password(token):
    result = _verify_reset_token(token)
    if not result:
        flash('This password reset link is invalid or has expired. Please request a new one.', 'error')
        return redirect(url_for('forgot_password'))

    user_id, role, email = result

    if request.method == 'POST':
        new_password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if len(new_password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return render_template('reset_password.html', token=token)

        if new_password != confirm_password:
            flash('Passwords do not match. Please try again.', 'error')
            return render_template('reset_password.html', token=token)

        hashed = generate_password_hash(new_password)

        if role == 'client':
            user = User.query.filter_by(email=email).first()
            if user:
                user.password = hashed
                db.session.commit()
        elif role == 'pro':
            pro = Professional.query.filter_by(email=email).first()
            if pro:
                pro.password = hashed
                db.session.commit()

        flash('Your password has been updated successfully! You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)


@app.route('/professional/delete-account/', methods=['POST'])
def delete_professional_account():
    if 'professional_id' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('login'))

    professional = Professional.query.get(session['professional_id'])
    if professional:
        db.session.delete(professional)
        db.session.commit()

    session.clear()
    flash('Your account has been permanently deleted.', 'success')
    return redirect(url_for('login'))


@app.route('/client/delete-account/', methods=['POST'])
def delete_client_account():
    if 'user_id' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if user:
        db.session.delete(user)
        db.session.commit()

    session.clear()
    flash('Your account has been permanently deleted.', 'success')
    return redirect(url_for('login'))

def render_signup_page(client_form=None, pro_form=None, active_tab='client'):
    if client_form is None:
        client_form = ClientSignupForm()
    if pro_form is None:
        pro_form = ProfessionalSignupForm()
    try:
        categories = ServiceCategory.query.all()
        pro_form.services.choices = [(c.service_category_id, c.service_category_name) for c in categories]
    except Exception as e:
        pro_form.services.choices = []
    return render_template('signup.html', client_form=client_form, pro_form=pro_form, active_tab=active_tab)

@app.route('/signup/')
def signup():
    tab = request.args.get('tab', 'client')
    return render_signup_page(active_tab=tab)

@app.route('/signup-client/', methods=['GET', 'POST'])
def signup_client():
    form = ClientSignupForm()
    if request.method == 'GET':
        return render_signup_page(client_form=form, active_tab='client')

    if form.validate_on_submit():
        existing_user = User.query.filter_by(email=form.email.data.lower()).first()
        if existing_user:
            flash('An account with this email already exists.', 'error')
            return render_signup_page(client_form=form, active_tab='client')

        new_user = User(
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            email=form.email.data.lower(),
            password=generate_password_hash(form.password.data),
            phone_number=form.phone.data
        )
        db.session.add(new_user)
        db.session.commit()

        # Send welcome email
        try:
            send_welcome_email(new_user.email, new_user.first_name)
        except Exception as e:
            print(f"Error sending welcome email: {e}")

        # Log the new client in right away
        new_user = User.query.filter_by(email=form.email.data.lower()).first()
        session['user_id'] = new_user.user_id
        session['user_name'] = f"{new_user.first_name} {new_user.last_name}"
        session['user_email'] = new_user.email

        # Check if this email already has a professional account too
        existing_professional = Professional.query.filter_by(email=form.email.data.lower()).first()
        if existing_professional:
            session['has_dual_account'] = True

        flash('Client signup submitted successfully!', 'success')
        return redirect(url_for('results'))

    return render_signup_page(client_form=form, active_tab='client')

@app.route('/signup-pro/', methods=['GET', 'POST'])
def signup_pro():
    form = ProfessionalSignupForm()
    try:
        categories = ServiceCategory.query.all()
        form.services.choices = [(c.service_category_id, c.service_category_name) for c in categories]
    except Exception as e:
        form.services.choices = []

    if request.method == 'GET':
        return render_signup_page(pro_form=form, active_tab='pro')

    if form.validate_on_submit():
        existing_professional = Professional.query.filter_by(email=form.email.data.lower()).first()
        if existing_professional:
            flash('A professional account with this email already exists.', 'error')
            return render_signup_page(pro_form=form, active_tab='pro')

        professional = Professional(
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            email=form.email.data.lower(),
            password=generate_password_hash(form.password.data),
            phone_number=form.phone.data,
            business_name=form.business_name.data,
            bio='',
            account_status='pending'
        )
        db.session.add(professional)
        db.session.flush()  # Get the professional_id before committing

        # Save selected services into ProfessionalService table
        for svc_id in form.services.data:
            ps = ProfessionalService(
                professional_id=professional.professional_id,
                service_category_id=svc_id,
                rate=0.0  # Default rate
            )
            db.session.add(ps)

        db.session.commit()

        # Send welcome email
        try:
            send_welcome_email(professional.email, professional.first_name)
        except Exception as e:
            print(f"Error sending welcome email: {e}")

        professional = Professional.query.filter_by(email=form.email.data.lower()).first()
        if professional:
            session['professional_id'] = professional.professional_id
            session['professional_name'] = f"{professional.first_name} {professional.last_name}"

        # Check if this email already has a client account too
        existing_user = User.query.filter_by(email=form.email.data.lower()).first()
        if existing_user:
            session['has_dual_account'] = True

        flash('Professional signup submitted successfully!', 'success')
        return redirect(url_for('find_jobs'))

    return render_signup_page(pro_form=form, active_tab='pro')


# ── Professional Profile Page ──────────────────────────────────────────────
@app.route('/professional/<int:professional_id>/profile/')
def professional_profile(professional_id):
    professional = Professional.query.get(professional_id)
    if not professional:
        flash('Professional not found.', 'error')
        return redirect(url_for('results'))

    # Get this professional's services
    service_names = []
    for ps in ProfessionalService.query.filter_by(professional_id=professional_id).all():
        cat = ServiceCategory.query.get(ps.service_category_id)
        if cat:
            service_names.append(cat.service_category_name)

    # Pass CometChat App ID and Region (safe to expose in frontend)
    cometchat_app_id = app.config.get('COMETCHAT_APP_ID', '')
    cometchat_region = app.config.get('COMETCHAT_REGION', '')
    paystack_public_key = app.config.get('PAYSTACK_PUBLIC_KEY', '')

    # Get the client's email and unpaid booking only if logged in
    client_email = ''
    latest_unpaid_booking = None
    if 'user_id' in session:
        current_user = User.query.get(session['user_id'])
        client_email = current_user.email if current_user else ''
        latest_unpaid_booking = Booking.query.filter_by(
            user_id=session['user_id'], 
            professional_id=professional_id, 
            payment_status='unpaid'
        ).order_by(Booking.booking_id.desc()).first()

    # Get all products and reviews for this professional
    products = Product.query.filter_by(professional_id=professional_id).all()
    reviews = Review.query.filter_by(professional_id=professional_id).order_by(Review.created_at.desc()).all()

    return render_template(
        'professional_profile.html',
        professional=professional,
        service_names=service_names,
        cometchat_app_id=cometchat_app_id,
        cometchat_region=cometchat_region,
        paystack_public_key=paystack_public_key,
        latest_unpaid_booking=latest_unpaid_booking,
        datetime=datetime,
        client_email=client_email,
        products=products,
        reviews=reviews
    )


@app.route('/professional/<int:professional_id>/hire/')
def professional_hire(professional_id):
    professional = Professional.query.get(professional_id)
    if not professional:
        flash('Professional not found.', 'error')
        return redirect(url_for('results'))

    service_names = []
    for ps in ProfessionalService.query.filter_by(professional_id=professional_id).all():
        cat = ServiceCategory.query.get(ps.service_category_id)
        if cat:
            service_names.append(cat.service_category_name)

    cometchat_app_id = app.config.get('COMETCHAT_APP_ID', '')
    cometchat_region = app.config.get('COMETCHAT_REGION', '')
    paystack_public_key = app.config.get('PAYSTACK_PUBLIC_KEY', '')

    client_email = ''
    latest_unpaid_booking = None
    if 'user_id' in session:
        current_user = User.query.get(session['user_id'])
        client_email = current_user.email if current_user else ''
        latest_unpaid_booking = Booking.query.filter_by(
            user_id=session['user_id'], 
            professional_id=professional_id, 
            payment_status='unpaid'
        ).order_by(Booking.booking_id.desc()).first()

    return render_template(
        'hire_artisan.html',
        professional=professional,
        service_names=service_names,
        cometchat_app_id=cometchat_app_id,
        cometchat_region=cometchat_region,
        paystack_public_key=paystack_public_key,
        latest_unpaid_booking=latest_unpaid_booking,
        datetime=datetime,
        client_email=client_email
    )


# ── CometChat Auth Token (keeps Auth Key secret on the server) ─────────────
@app.route('/cometchat/auth-token/', methods=['POST'])
def cometchat_auth_token():
    # Only logged-in clients can get a token
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # CometChat user ID for this client
    uid  = f"user-{user.user_id}"
    name = f"{user.first_name} {user.last_name}"

    app_id   = app.config['COMETCHAT_APP_ID']
    region   = app.config['COMETCHAT_REGION']
    auth_key = app.config['COMETCHAT_AUTH_KEY']

    base_url = f"https://api-{region}.cometchat.io/v3"
    headers  = {
        "appId": app_id,
        "apiKey": auth_key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Step 1: Create the CLIENT user in CometChat (safe to call even if already exists)
    r1 = requests.post(f"{base_url}/users", headers=headers, json={"uid": uid, "name": name})
    print(f"[CometChat] Create client user: {r1.status_code} {r1.text}")

    # Step 2: Also create the PROFESSIONAL user so chat can work between both sides
    # We get the professional_id from the form data sent by the page
    pro_id = request.form.get('professional_id')
    if pro_id:
        professional = Professional.query.get(int(pro_id))
        if professional:
            pro_uid  = f"pro-{professional.professional_id}"
            pro_name = f"{professional.first_name} {professional.last_name}"
            r2 = requests.post(f"{base_url}/users", headers=headers, json={"uid": pro_uid, "name": pro_name})
            print(f"[CometChat] Create pro user: {r2.status_code} {r2.text}")

    # Step 3: Generate an auth token for the client user
    token_response = requests.post(f"{base_url}/users/{uid}/auth_tokens", headers=headers)
    data = token_response.json()
    print(f"[CometChat] Auth token response: {token_response.status_code} {token_response.text}")

    auth_token = data.get('data', {}).get('authToken')
    if not auth_token:
        return jsonify({'error': 'Could not generate token', 'detail': data}), 500

    return jsonify({'uid': uid, 'authToken': auth_token})


# ── Professional CometChat Auth Token ──────────────────────────────────────
@app.route('/cometchat/pro-auth-token/', methods=['POST'])
def cometchat_pro_auth_token():
    # Only logged-in professionals can get a token
    if 'professional_id' not in session:
        return jsonify({'error': 'Not logged in as professional'}), 401

    professional = Professional.query.get(session['professional_id'])
    if not professional:
        return jsonify({'error': 'Professional not found'}), 404

    uid  = f"pro-{professional.professional_id}"
    name = f"{professional.first_name} {professional.last_name}"

    app_id   = app.config['COMETCHAT_APP_ID']
    region   = app.config['COMETCHAT_REGION']
    auth_key = app.config['COMETCHAT_AUTH_KEY']

    base_url = f"https://api-{region}.cometchat.io/v3"
    headers  = {
        "appId": app_id,
        "apiKey": auth_key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Create the professional user in CometChat
    r1 = requests.post(f"{base_url}/users", headers=headers, json={"uid": uid, "name": name})
    print(f"[CometChat] Create pro user: {r1.status_code} {r1.text}")

    # Generate an auth token for the professional
    token_response = requests.post(f"{base_url}/users/{uid}/auth_tokens", headers=headers)
    data = token_response.json()
    print(f"[CometChat] Pro auth token response: {token_response.status_code} {token_response.text}")

    auth_token = data.get('data', {}).get('authToken')
    if not auth_token:
        return jsonify({'error': 'Could not generate token', 'detail': data}), 500

    return jsonify({'uid': uid, 'authToken': auth_token})


@app.route('/api/banks/', methods=['GET'])
@app.route('/api/paystack/banks/', methods=['GET'])
def get_paystack_banks():
    """Server-side proxy to fetch the list of Nigerian banks from Paystack.
    This avoids exposing the Paystack secret key to the browser.
    Returns JSON: { status: 'success', data: [ { name, code, slug }, ... ] }
    """
    key = app.config.get('PAYSTACK_SECRET_KEY')
    if not key:
        return jsonify({'status': 'error', 'message': 'Paystack key not configured'}), 500

    url = "https://api.paystack.co/bank?country=nigeria"
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            banks = data.get('data', []) or []
            # Only return active banks and a small shape
            active_banks = []
            for b in banks:
                if b.get('active'):
                    active_banks.append({
                        'name': b.get('name'),
                        'code': b.get('code'),
                        'slug': b.get('slug')
                    })
            return jsonify({'status': 'success', 'data': active_banks})
        else:
            return jsonify({'status': 'error', 'message': 'Paystack API error', 'detail': resp.text}), 502
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/resolve-account/', methods=['GET'])
def resolve_account():
    """Resolve account number -> account name via Paystack. Expects query params: account_number, bank_code"""
    if 'professional_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    account_number = request.args.get('account_number', '').strip()
    bank_code = request.args.get('bank_code', '').strip()
    if not account_number or not bank_code:
        return jsonify({'status': 'error', 'message': 'Please provide both account_number and bank_code'}), 400

    # validate account number
    if not account_number.isdigit() or len(account_number) != 10:
        return jsonify({'status': 'error', 'message': 'Please enter a valid 10-digit account number'}), 400

    url = f"https://api.paystack.co/bank/resolve?account_number={account_number}&bank_code={bank_code}"
    headers = {"Authorization": f"Bearer {app.config.get('PAYSTACK_SECRET_KEY')}", "Accept": "application/json"}
    try:
        app.logger.debug(f"Resolving account: account_number={account_number}, bank_code={bank_code}")
        app.logger.debug(f"Using PAYSTACK_SECRET_KEY present: {bool(app.config.get('PAYSTACK_SECRET_KEY'))}")
        resp = requests.get(url, headers=headers, timeout=10)
        try:
            data = resp.json()
        except Exception:
            app.logger.error(f"Paystack resolve returned non-json (status {resp.status_code}): {resp.text}")
            return jsonify({'status': 'error', 'message': 'Invalid response from Paystack', 'detail': resp.text}), 502

        app.logger.debug(f"Paystack resolve response: status={resp.status_code} body={data}")
        if resp.status_code == 200 and data.get('status') is True:
            acct_name = data.get('data', {}).get('account_name')
            return jsonify({'status': 'success', 'account_name': acct_name, 'data': data.get('data')}), 200
        else:
            app.logger.error(f"Paystack resolve failed: status={resp.status_code} body={data}")
            return jsonify({'status': 'error', 'message': data.get('message', 'Verification failed'), 'detail': data}), 400
    except Exception as e:
        app.logger.exception('Exception while resolving account')
        return jsonify({'status': 'error', 'message': str(e)}), 500


def create_or_update_recipient(professional, bank_code, bank_name, account_number, account_name):
    """Single source of truth for creating a Paystack transfer recipient.
    Used by both /api/withdrawal-settings/ and the Edit Profile form so that
    recipient_code is NEVER set/bypassed without a successful Paystack call.
    Returns (success: bool, recipient_code_or_error_message: str)
    """
    if not (bank_code and account_number and account_name):
        return False, 'Please provide bank_code, account_number and account_name'

    if not account_number.isdigit() or len(account_number) != 10:
        return False, 'Please enter a valid 10-digit account number'

    url = 'https://api.paystack.co/transferrecipient'
    headers = {
        'Authorization': f"Bearer {app.config.get('PAYSTACK_SECRET_KEY')}",
        'Content-Type': 'application/json'
    }
    body = {
        'type': 'nuban',
        'name': account_name,
        'account_number': account_number,
        'bank_code': bank_code,
        'currency': 'NGN'
    }
    try:
        app.logger.debug(f"Creating Paystack transfer recipient with body: {body}")
        r = requests.post(url, headers=headers, json=body, timeout=10)
        try:
            data = r.json()
        except Exception:
            app.logger.error(f"Paystack transferrecipient returned non-json (status {r.status_code}): {r.text}")
            return False, 'Invalid response from Paystack'

        app.logger.debug(f"Paystack transferrecipient response: status={r.status_code} body={data}")
        if r.status_code in (200, 201) and data.get('status') is True:
            recipient_code = data.get('data', {}).get('recipient_code')
            professional.bank_name = bank_name
            professional.bank_code = bank_code
            professional.account_number = account_number
            professional.account_name = account_name
            professional.recipient_code = recipient_code
            try:
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                app.logger.exception('Failed to commit professional bank changes to DB')
                return False, f'Failed to save bank details: {exc}'
            return True, recipient_code
        else:
            app.logger.error(f"Paystack recipient creation failed: status={r.status_code} body={data}")
            return False, data.get('message', 'Paystack recipient creation failed')
    except Exception as e:
        app.logger.exception('Exception while creating transfer recipient')
        return False, str(e)


@app.route('/api/withdrawal-settings/', methods=['POST'])
def save_withdrawal_settings():
    """Save bank details and create Paystack transfer recipient.
    Expects JSON: { bank_code, bank_name, account_number, account_name }
    """
    if 'professional_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    payload = request.get_json() or {}
    professional = Professional.query.get(session['professional_id'])
    if not professional:
        return jsonify({'status': 'error', 'message': 'Professional not found'}), 404

    success, result = create_or_update_recipient(
        professional,
        payload.get('bank_code') or '',
        payload.get('bank_name') or '',
        payload.get('account_number') or '',
        payload.get('account_name') or ''
    )
    if success:
        return jsonify({'status': 'success', 'recipient_code': result}), 200
    return jsonify({'status': 'error', 'message': result}), 400


def payoutFromEscrow(professional_id, amount_kobo):
    """Initiate a transfer from Paystack escrow to the saved recipient_code for a professional.
    amount_kobo: integer amount in kobo/pennies (NGN * 100).
    """
    professional = Professional.query.get(professional_id)
    if not professional or not professional.recipient_code:
        raise ValueError('Recipient not configured')

    url = 'https://api.paystack.co/transfer'
    headers = {
        'Authorization': f"Bearer {app.config.get('PAYSTACK_SECRET_KEY')}",
        'Content-Type': 'application/json'
    }
    body = {
        'source': 'balance',
        'amount': int(amount_kobo),
        'recipient': professional.recipient_code,
        'reason': f'Payout to professional {professional.professional_id}'
    }
    resp = requests.post(url, headers=headers, json=body, timeout=15)
    try:
        data = resp.json()
    except Exception:
        app.logger.error(f"Paystack transfer returned non-json (status {resp.status_code}): {resp.text}")
        data = {'raw': resp.text}
    app.logger.debug(f"Paystack transfer response: status={resp.status_code} body={data}")
    return resp.status_code, data


@app.route('/client/release-payment/<int:booking_id>/', methods=['POST'])
def client_release_payment(booking_id):
    # Only the booking's client can release payment
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    booking = Booking.query.get(booking_id)
    if not booking or booking.user_id != session['user_id']:
        return jsonify({'status': 'error', 'message': 'Booking not found'}), 404

    if booking.payment_status != 'paid':
        return jsonify({'status': 'error', 'message': 'Booking is not paid'}), 400

    if booking.job_status != 'completed':
        return jsonify({'status': 'error', 'message': 'Job not marked completed'}), 400

    if booking.is_refunded:
        return jsonify({'status': 'error', 'message': 'Booking has been refunded'}), 400

    if getattr(booking, 'is_paid_out', False):
        return jsonify({'status': 'error', 'message': 'Payout already processed'}), 400

    professional = booking.professional
    if not professional or not professional.recipient_code:
        return jsonify({'status': 'error', 'message': 'Professional payout not configured'}), 400

    # Calculate transfer amount: 90% to professional
    try:
        amt = float(booking.booking_price or 0.0)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Invalid booking amount'}), 400

    pro_amount = round(amt * 0.90, 2)
    amount_kobo = int(pro_amount * 100)

    status_code, data = payoutFromEscrow(professional.professional_id, amount_kobo)
    if status_code in (200,201) and data.get('status'):
        # Try to extract a reference
        ref = data.get('data', {}).get('reference') or data.get('data', {}).get('transfer_code') or str(data.get('data', {}))
        booking.is_paid_out = True
        booking.payout_reference = ref
        payout = Payout(
            booking_id=booking.booking_id,
            professional_id=professional.professional_id,
            amount=pro_amount,
            status='success',
            reference=ref,
            response=json.dumps(data)[:2000],
            attempts=1
        )
        db.session.add(payout)
        db.session.commit()

        # Send payout confirmation email to the artisan
        send_payout_email(
            professional.email,
            f"{professional.first_name} {professional.last_name}",
            pro_amount,
            booking.booking_id,
            professional.bank_name,
            professional.account_number,
            ref
        )

        return jsonify({'status': 'success', 'message': 'Payout initiated', 'detail': data}), 200
    else:
        try:
            payout = Payout(
                booking_id=booking.booking_id,
                professional_id=professional.professional_id,
                amount=pro_amount,
                status='failed',
                response=json.dumps(data)[:2000],
                attempts=1
            )
            db.session.add(payout)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Failed to log failed payout record')
        return jsonify({'status': 'error', 'message': 'Transfer failed', 'detail': data}), 400


# ── Professional Inbox (view all conversations) ────────────────────────────
@app.route('/professional/inbox/')
def professional_inbox():
    if 'professional_id' not in session:
        flash('Please log in as a professional to access your inbox.', 'error')
        return redirect(url_for('login'))

    professional = Professional.query.get(session['professional_id'])
    if not professional:
        flash('Professional not found.', 'error')
        return redirect(url_for('logout'))

    # Get all bookings for this professional, with user info
    bookings = Booking.query.filter_by(professional_id=professional.professional_id).order_by(Booking.booking_id.desc()).all()

    # Build a list of unique clients who have booked this professional
    clients = []
    seen_user_ids = set()
    for booking in bookings:
        if booking.user_id not in seen_user_ids:
            seen_user_ids.add(booking.user_id)
            clients.append({
                'user': booking.user,
                'latest_booking': booking,
                'booking_count': Booking.query.filter_by(professional_id=professional.professional_id, user_id=booking.user_id).count()
            })

    cometchat_app_id = app.config['COMETCHAT_APP_ID']
    cometchat_region = app.config['COMETCHAT_REGION']

    return render_template(
        'professional_inbox.html',
        professional=professional,
        clients=clients,
        cometchat_app_id=cometchat_app_id,
        cometchat_region=cometchat_region
    )


# ── Client Books a Professional ────────────────────────────────────────────
@app.route('/client/book/<int:professional_id>/', methods=['POST'])
def book_professional(professional_id):
    if 'user_id' not in session:
        flash('Please log in to book a professional.', 'error')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    professional = Professional.query.get(professional_id)
    if not professional:
        flash('Professional not found.', 'error')
        return redirect(url_for('results'))

    # Get the professional's first service (or let client pick)
    prof_service = ProfessionalService.query.filter_by(professional_id=professional_id).first()
    if not prof_service:
        flash('This professional has no services listed yet.', 'error')
        return redirect(url_for('professional_profile', professional_id=professional_id))

    scheduled_date_str = request.form.get('scheduled_date', '')
    address = request.form.get('address', '').strip()
    booking_price = request.form.get('booking_price', '').strip()

    if not scheduled_date_str:
        flash('Please select a date for the booking.', 'error')
        return redirect(url_for('professional_profile', professional_id=professional_id))

    try:
        scheduled_date = datetime.datetime.strptime(scheduled_date_str, '%Y-%m-%d')
    except ValueError:
        flash('Invalid date format.', 'error')
        return redirect(url_for('professional_profile', professional_id=professional_id))

    price = float(booking_price) if booking_price else float(prof_service.rate or 0.0)

    booking = Booking(
        user_id=user.user_id,
        professional_id=professional_id,
        professional_service_id=prof_service.professional_service_id,
        scheduled_date=scheduled_date,
        booking_price=price,
        address=address or user.phone_number,
        job_status='pending'
    )
    db.session.add(booking)
    db.session.commit()

    # Send email notifications to both parties
    service_name = prof_service.service_category.service_category_name if prof_service.service_category else 'Service'
    formatted_date = scheduled_date.strftime('%A, %d %B %Y')
    pro_full_name = f"{professional.first_name} {professional.last_name}"
    client_full_name = f"{user.first_name} {user.last_name}"

    try:
        send_new_booking_email_to_professional(
            professional.email, pro_full_name, client_full_name,
            service_name, formatted_date, address, price, booking.booking_id
        )
    except Exception as e:
        print(f"Error sending booking email to professional: {e}")

    try:
        send_new_booking_email_to_client(
            user.email, client_full_name, pro_full_name,
            professional.business_name or pro_full_name,
            service_name, formatted_date, address, price, booking.booking_id
        )
    except Exception as e:
        print(f"Error sending booking confirmation to client: {e}")

    flash(f'Booking request sent to {professional.first_name}! They will review and respond shortly.', 'success')
    return redirect(url_for('professional_profile', professional_id=professional_id))

# ── Client Bookings Page ────────────────────────────────────────────
@app.route('/client/bookings/')
def client_bookings():
    if 'user_id' not in session:
        flash('Please log in to view your bookings.', 'error')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    bookings = Booking.query.filter_by(user_id=user.user_id).order_by(Booking.booking_id.desc()).all()

    cometchat_app_id = app.config['COMETCHAT_APP_ID']
    cometchat_region = app.config['COMETCHAT_REGION']
    paystack_public_key = app.config.get('PAYSTACK_PUBLIC_KEY', '')

    return render_template(
        'client_bookings.html', 
        user=user, 
        bookings=bookings, 
        cometchat_app_id=cometchat_app_id, 
        cometchat_region=cometchat_region,
        paystack_public_key=paystack_public_key
    )

# ── Verify Paystack Payment ─────────────────────────────────────────
@app.route('/client/verify-payment/<int:booking_id>', methods=['POST'])
def verify_payment(booking_id):
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401
    
    booking = Booking.query.get(booking_id)
    if not booking or booking.user_id != session['user_id']:
        return jsonify({'status': 'error', 'message': 'Booking not found'}), 404

    reference = request.json.get('reference')
    if not reference:
        return jsonify({'status': 'error', 'message': 'No reference provided'}), 400

    # Anti-replay check: ensure this reference wasn't already used on another booking
    already_used = Booking.query.filter(
        Booking.payment_reference == reference,
        Booking.booking_id != booking.booking_id
    ).first()
    if already_used:
        return jsonify({'status': 'error', 'message': 'Payment reference has already been used'}), 400
        
    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {
        "Authorization": f"Bearer {app.config.get('PAYSTACK_SECRET_KEY')}"
    }
    resp = requests.get(url, headers=headers)
    
    if resp.status_code == 200:
        data = resp.json()
        if data.get('status') is True and data.get('data', {}).get('status') == 'success':
            paid_amount_kobo = data.get('data', {}).get('amount', 0)
            expected_amount_kobo = int(float(booking.booking_price or 0.0) * 100)

            # Security check: verify the paid amount matches what was booked
            if paid_amount_kobo < expected_amount_kobo:
                return jsonify({'status': 'error', 'message': 'Paid amount is less than booking price'}), 400

            booking.payment_status = 'paid'
            booking.payment_reference = reference
            db.session.commit()

            # Send official payment receipt email to client
            if booking.user:
                pro = booking.professional
                pro_name = f"{pro.first_name} {pro.last_name}" if pro else "Assigned Professional"
                bus_name = pro.business_name if pro else ""
                sched_date = booking.scheduled_date.strftime('%b %d, %Y') if booking.scheduled_date else "Scheduled with Artisan"
                send_client_payment_receipt_email(
                    booking.user.email,
                    booking.user.first_name,
                    float(booking.booking_price or 0.0),
                    booking.booking_id,
                    pro_name,
                    bus_name,
                    sched_date,
                    booking.address or "",
                    reference
                )

            return jsonify({'status': 'success', 'message': 'Payment successful!'})
    
    return jsonify({'status': 'error', 'message': 'Payment verification failed'}), 400

# ── Professional Refunds a Booking ─────────────────────────────────────────
@app.route('/professional/refund/<int:booking_id>/', methods=['POST'])
def refund_client(booking_id):
    if 'professional_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    booking = Booking.query.get(booking_id)
    if not booking or booking.professional_id != session['professional_id']:
        return jsonify({'status': 'error', 'message': 'Booking not found'}), 404

    if booking.payment_status != 'paid':
        return jsonify({'status': 'error', 'message': 'Booking is not paid'}), 400

    if booking.is_refunded:
        return jsonify({'status': 'error', 'message': 'Already refunded'}), 400

    if not booking.payment_reference:
        return jsonify({'status': 'error', 'message': 'Payment reference not found. Manual refund required.'}), 400

    url = "https://api.paystack.co/refund"
    headers = {
        "Authorization": f"Bearer {app.config.get('PAYSTACK_SECRET_KEY')}",
        "Content-Type": "application/json"
    }
    payload = {
        "transaction": booking.payment_reference,
        "amount": int(booking.booking_price * 100) # Full refund
    }

    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code in [200, 201]:
        data = resp.json()
        if data.get('status') == True:
            booking.is_refunded = True
            db.session.commit()
            return jsonify({'status': 'success', 'message': 'Refund initiated successfully!'})
    else:
        # Paystack might return an error if it's already refunded or not allowed
        try:
            err_msg = resp.json().get('message', 'Refund failed')
        except:
            err_msg = 'Refund failed'
        return jsonify({'status': 'error', 'message': err_msg}), 400

    return jsonify({'status': 'error', 'message': 'Refund failed'}), 400

# ── User Edits Booking Price ────────────────────────────────────────
@app.route('/booking/<int:booking_id>/edit-price/', methods=['POST'])
@csrf.exempt
def edit_booking_price(booking_id):
    user_type = None
    if 'professional_id' in session:
        user_type = 'professional'
    elif 'user_id' in session:
        user_type = 'client'
    else:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'status': 'error', 'message': 'Booking not found'}), 404

    # Authorization
    if user_type == 'professional' and booking.professional_id != session['professional_id']:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    if user_type == 'client' and booking.user_id != session['user_id']:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    if booking.payment_status == 'paid':
        return jsonify({'status': 'error', 'message': 'Cannot edit price for a paid booking'}), 400

    new_price = request.json.get('new_price')
    try:
        new_price = float(new_price)
        if new_price < 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Invalid price'}), 400

    old_price = booking.booking_price
    booking.booking_price = new_price
    # Track who changed the price
    if user_type == 'professional':
        booking.price_updated = True
        booking.price_updated_by = 'professional'
    elif user_type == 'client':
        booking.price_updated = True
        booking.price_updated_by = 'client'
    db.session.commit()

    # Determine who is the sender and receiver for the notification
    sender_uid = f"pro-{booking.professional_id}" if user_type == 'professional' else f"user-{booking.user_id}"
    receiver_uid = f"user-{booking.user_id}" if user_type == 'professional' else f"pro-{booking.professional_id}"
    
    # Get name of the person who changed the price
    changer_name = ''
    if user_type == 'professional':
        prof = Professional.query.get(booking.professional_id)
        changer_name = f"{prof.first_name} {prof.last_name}" if prof else 'The professional'
    else:
        client = User.query.get(booking.user_id)
        changer_name = f"{client.first_name} {client.last_name}" if client else 'The client'

    # Automatically notify the other party via CometChat
    try:
        base_url = f"https://{app.config['COMETCHAT_APP_ID']}.api-{app.config['COMETCHAT_REGION']}.cometchat.io/v3"
        headers = {
            "apikey": app.config['COMETCHAT_AUTH_KEY'],
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Send notification message about price change with identifiable prefix
        # Prefix: PRICE_PRO_UPDATE or PRICE_CLIENT_UPDATE for easy frontend parsing
        prefix = "PRICE_PRO_UPDATE" if user_type == 'professional' else "PRICE_CLIENT_UPDATE"
        msg_text = f"[{prefix}] Booking #{booking.booking_id}|{old_price:,.2f}|{new_price:,.2f}|{changer_name}"
        
        # Create the user first if needed via REST API
        requests.post(f"{base_url}/users", headers=headers, json={"uid": sender_uid, "name": changer_name})
        
        payload = {
            "category": "message",
            "type": "text",
            "receiver": receiver_uid,
            "receiverType": "user",
            "sender": sender_uid,
            "data": {
                "text": msg_text
            }
        }
        requests.post(f"{base_url}/messages", headers=headers, json=payload, timeout=5)
    except Exception as e:
        print(f"[CometChat] Notification error: {e}")

    return jsonify({'status': 'success', 'message': f'Price updated from ₦{old_price:,.2f} to ₦{new_price:,.2f}!'})

# ── Client acknowledges price update ────────────────────────────────────────
@app.route('/booking/<int:booking_id>/acknowledge-price-update/', methods=['POST'])
@csrf.exempt
def acknowledge_price_update(booking_id):
    if 'user_id' not in session and 'professional_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'status': 'error', 'message': 'Booking not found'}), 404

    booking.price_updated = False
    booking.price_updated_by = None
    db.session.commit()

    return jsonify({'status': 'success'})

# ── Professional views their bookings ──────────────────────────────────────
@app.route('/professional/bookings/')
def professional_bookings():
    if 'professional_id' not in session:
        flash('Please log in as a professional.', 'error')
        return redirect(url_for('login'))

    professional = Professional.query.get(session['professional_id'])
    if not professional:
        flash('Professional not found.', 'error')
        return redirect(url_for('logout'))

    bookings = Booking.query.filter_by(professional_id=professional.professional_id).order_by(Booking.booking_id.desc()).all()

    cometchat_app_id = app.config['COMETCHAT_APP_ID']
    cometchat_region = app.config['COMETCHAT_REGION']

    return render_template('professional_bookings.html', professional=professional, bookings=bookings, cometchat_app_id=cometchat_app_id, cometchat_region=cometchat_region)


# ── Professional Chat Page (dedicated page per booking) ────────────────────
@app.route('/professional/chat/<int:booking_id>/')
def professional_chat(booking_id):
    if 'professional_id' not in session:
        flash('Please log in as a professional.', 'error')
        return redirect(url_for('login'))

    professional = Professional.query.get(session['professional_id'])
    if not professional:
        flash('Professional not found.', 'error')
        return redirect(url_for('logout'))

    booking = Booking.query.get(booking_id)
    if not booking or booking.professional_id != professional.professional_id:
        flash('Booking not found.', 'error')
        return redirect(url_for('find_jobs'))

    cometchat_app_id = app.config['COMETCHAT_APP_ID']
    cometchat_region = app.config['COMETCHAT_REGION']

    # Get all services this professional offers
    prof_service_names = []
    for ps in ProfessionalService.query.filter_by(professional_id=professional.professional_id).all():
        cat = ServiceCategory.query.get(ps.service_category_id)
        if cat:
            prof_service_names.append(cat.service_category_name)

    return render_template(
        'professional_chat.html',
        professional=professional,
        booking=booking,
        client=booking.user,
        prof_service_names=prof_service_names,
        cometchat_app_id=cometchat_app_id,
        cometchat_region=cometchat_region
    )


# ── Professional updates booking status ────────────────────────────────────
@app.route('/professional/booking/<int:booking_id>/update-status/', methods=['POST'])
def update_booking_status(booking_id):
    if 'professional_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    booking = Booking.query.get(booking_id)
    if not booking or booking.professional_id != session['professional_id']:
        return jsonify({'error': 'Booking not found'}), 404

    new_status = request.form.get('status', '')
    if new_status not in ['pending', 'in-progress', 'completed']:
        return jsonify({'error': 'Invalid status'}), 400

    previous_status = booking.job_status
    booking.job_status = new_status
    if new_status == 'completed':
        booking.completion_date = datetime.datetime.now()

    db.session.commit()

    if new_status == 'completed' and previous_status != 'completed':
        client = booking.user
        professional = booking.professional
        if client and professional:
            send_job_completion_email(
                client_email=client.email,
                client_name=f"{client.first_name} {client.last_name}".strip(),
                professional_name=f"{professional.first_name} {professional.last_name}".strip(),
                booking_id=booking.booking_id,
                professional_id=professional.professional_id
            )

    flash(f'Booking #{booking.booking_id} updated to {new_status}.', 'success')
    return redirect(url_for('professional_bookings'))

# ── Client Reviews Professional ────────────────────────────────────────────
@app.route('/client/review/<int:booking_id>/', methods=['POST'])
def review_professional(booking_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    booking = Booking.query.get(booking_id)
    if not booking or booking.user_id != session['user_id']:
        return jsonify({'error': 'Booking not found'}), 404

    if booking.job_status != 'completed':
        return jsonify({'error': 'Only completed jobs can be reviewed'}), 400

    if booking.review:
        return jsonify({'error': 'You have already reviewed this booking'}), 400

    data = request.json
    rating = data.get('rating')
    review_text = data.get('review_text', '')

    if not rating or not (1 <= int(rating) <= 5):
        return jsonify({'error': 'Rating must be between 1 and 5'}), 400

    review = Review(
        user_id=booking.user_id,
        professional_id=booking.professional_id,
        booking_id=booking_id,
        rating=int(rating),
        review_text=review_text
    )
    db.session.add(review)
    db.session.commit()

    # Recalculate average rating for professional
    prof = Professional.query.get(booking.professional_id)
    reviews = Review.query.filter_by(professional_id=prof.professional_id).all()
    if reviews:
        avg = sum(r.rating for r in reviews) / len(reviews)
        prof.average_rating = round(avg, 1)
        db.session.commit()

    return jsonify({'status': 'success', 'message': 'Review submitted successfully!'})


@app.route('/client/complaint/<int:booking_id>/', methods=['GET', 'POST'])
def client_complaint(booking_id):
    if 'user_id' not in session:
        flash('Please log in to file a complaint.', 'error')
        return redirect(url_for('login'))

    booking = Booking.query.get(booking_id)
    if not booking or booking.user_id != session['user_id']:
        flash('Booking not found.', 'error')
        return redirect(url_for('client_bookings'))

    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        if not subject or not message:
            flash('Please provide both a subject and a message.', 'error')
            return render_template('client_complaint.html', booking=booking)

        complaint = Complaint(
            user_id=booking.user_id,
            professional_id=booking.professional_id,
            booking_id=booking.booking_id,
            subject=subject,
            message=message,
            status='open'
        )
        db.session.add(complaint)
        db.session.commit()

        # Send confirmation email to the client
        if booking.user:
            send_complaint_received_email(
                booking.user.email,
                booking.user.first_name,
                booking.booking_id,
                subject
            )

        flash('Your complaint has been submitted to the admin team.', 'success')
        return redirect(url_for('client_bookings'))

    return render_template('client_complaint.html', booking=booking)


# ==========================================
# PERSONAL CATALOG / PORTFOLIO ROUTES
# ==========================================

@app.route('/professional/products/add/', methods=['POST'])
def add_product():
    if 'professional_id' not in session:
        flash('You must be logged in as a professional.', 'error')
        return redirect(url_for('login'))

    professional_id = session['professional_id']
    product_name = request.form.get('product_name')
    description = request.form.get('description')
    price = request.form.get('price')
    image_file = request.files.get('product_image')

    if not product_name or not price:
        flash('Name and price are required.', 'error')
        return redirect(url_for('edit_professional'))

    filename = None
    if image_file and image_file.filename != '':
        filename = save_secure_image(image_file)
        if not filename:
            flash('Invalid image format. Please upload a valid image (JPG, PNG, etc).', 'error')
            return redirect(url_for('edit_professional'))

    new_product = Product(
        professional_id=professional_id,
        product_name=product_name,
        description=description,
        price=float(price),
        product_image=filename
    )
    db.session.add(new_product)
    db.session.commit()
    flash('Item added to your catalog successfully!', 'success')
    return redirect(url_for('edit_professional'))

@app.route('/professional/products/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    if 'professional_id' not in session:
        return redirect(url_for('login'))

    product = Product.query.get_or_404(product_id)
    if product.professional_id != session['professional_id']:
        flash('Unauthorized access.', 'error')
        return redirect(url_for('edit_professional'))

    if product.product_image:
        import os
        try:
            os.remove(os.path.join(app.root_path, 'static', 'uploads', product.product_image))
        except:
            pass

    db.session.delete(product)
    db.session.commit()
    flash('Item deleted from your catalog.', 'success')
    return redirect(url_for('edit_professional'))


# ==========================================
# CUSTOM ERROR HANDLERS (404, 500, 503)
# ==========================================

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

@app.errorhandler(503)
def service_unavailable(e):
    return render_template('503.html'), 503

