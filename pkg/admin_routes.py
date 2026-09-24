# ==========================================
# ADMIN PANEL URLs — QUICK REFERENCE
# ==========================================
# Login:     http://127.0.0.1:5057/admin/login/
# ==========================================

# ==========================================
# EMAIL HELPER FUNCTIONS
# We use this to send approval emails to professionals!
# ==========================================
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import render_template, current_app

def send_email_via_smtp(to_email, subject, html_body):
    # Step 1: Grab our Gmail credentials from config.py
    sender = current_app.config.get('MAIL_DEFAULT_SENDER')
    password = current_app.config.get('MAIL_PASSWORD')
    server_address = current_app.config.get('MAIL_SERVER')
    port = current_app.config.get('MAIL_PORT')
    
    # Step 2: Build the Email Message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = to_email
    msg.attach(MIMEText(html_body, 'html'))
    
    # Step 3: Send it using Python's built-in smtplib
    try:
        server = smtplib.SMTP(server_address, port)
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, to_email, msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Oops! Failed to send email: {e}")

def send_verification_email(to_email, first_name):
    # Render our verified.html template and send it!
    html_body = render_template('emails/verified.html', first_name=first_name)
    send_email_via_smtp(to_email, "Your Account is Verified!", html_body)

def send_suspension_email(to_email, first_name):
    html_body = render_template('emails/suspended.html', first_name=first_name)
    send_email_via_smtp(to_email, "Your Kiraar Account Has Been Suspended", html_body)

def send_unsuspension_email(to_email, first_name):
    html_body = render_template('emails/unsuspended.html', first_name=first_name)
    send_email_via_smtp(to_email, "Your Kiraar Account Has Been Reinstated", html_body)

def send_complaint_status_email(client_email, client_name, booking_id, subject, new_status):
    """Notify client when admin updates the status of their complaint."""
    try:
        html_body = render_template('emails/complaint_status_update.html', client_name=client_name, booking_id=booking_id, subject=subject, new_status=new_status)
        send_email_via_smtp(client_email, f"Complaint Update - Booking #{booking_id} ({new_status.capitalize()})", html_body)
    except Exception as e:
        print(f"Failed to send complaint status email: {e}")

import os
import secrets

from flask import render_template, request, flash, redirect, session, jsonify, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from pkg import app
from pkg.forms import AdminLoginForm
from pkg.models import db, Admin, User, Professional, Booking, ServiceCategory, Product, Complaint



@app.route('/admin/login/', methods=['GET', 'POST'])
def admin_login():
    # If already logged in as admin, redirect to dashboard
    if 'admin_id' in session:
        return redirect(url_for('admin_dashboard'))

    form = AdminLoginForm()
    if form.validate_on_submit():
        admin = Admin.query.filter_by(email=form.email.data.lower()).first()
        if admin and check_password_hash(admin.password, form.password.data):
            session.permanent = True
            session['admin_id'] = admin.admin_id
            session['admin_email'] = admin.email
            flash('Welcome to the Admin Dashboard!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials.', 'error')

    return render_template('admin_login.html', form=form)


@app.route('/admin/logout/')
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_email', None)
    flash('You have been logged out of the admin panel.', 'success')
    return redirect(url_for('admin_login'))


@app.route('/admin/dashboard/')
def admin_dashboard():
    if 'admin_id' not in session:
        flash('Please log in as admin first.', 'error')
        return redirect(url_for('admin_login'))

    # ── Statistics ──────────────────────────────────────────────────────────
    total_users = User.query.count()
    total_professionals = Professional.query.count()
    total_bookings = Booking.query.count()
    total_service_categories = ServiceCategory.query.count()

    pending_bookings = Booking.query.filter_by(job_status='pending').count()
    in_progress_bookings = Booking.query.filter_by(job_status='in-progress').count()
    completed_bookings = Booking.query.filter_by(job_status='completed').count()

    paid_bookings = Booking.query.filter_by(payment_status='paid').count()
    unpaid_bookings = Booking.query.filter_by(payment_status='unpaid').count()

    # ── Professional verifications ──────────────────────────────────────────
    pending_verifications = Professional.query.filter_by(account_status='pending').count()
    verified_professionals = Professional.query.filter_by(account_status='verified').count()
    suspended_professionals = Professional.query.filter_by(account_status='suspended').count()
    unverified_professionals = Professional.query.filter_by(account_status='pending').all()
    all_professionals = Professional.query.all()
    all_users = User.query.all()

    # ── Recent bookings (last 10) ───────────────────────────────────────────
    recent_bookings = Booking.query.order_by(Booking.booking_id.desc()).limit(10).all()

    # ── All service categories ──────────────────────────────────────────────
    service_categories = ServiceCategory.query.all()

    # ── Products & Jobs uploaded by professionals ───────────────────────────
    # These are the portfolio items / product listings professionals upload
    all_products = Product.query.order_by(Product.product_id.desc()).all()
    total_products = len(all_products)

    # ── Real revenue from paid bookings (was previously a flat estimate) ────
    total_revenue = db.session.query(
        db.func.coalesce(db.func.sum(Booking.booking_price), 0)
    ).filter_by(payment_status='paid').scalar()

    # ── Refund Analytics ────────────────────────────────────────────────────
    total_refunded_count = Booking.query.filter_by(is_refunded=True).count()
    total_refunded_amount = db.session.query(
        db.func.coalesce(db.func.sum(Booking.booking_price), 0)
    ).filter_by(is_refunded=True).scalar()

    # ── Complaints ────────────────────────────────────────────────────────
    all_complaints = Complaint.query.order_by(Complaint.created_at.desc()).all()
    open_complaints_count = Complaint.query.filter_by(status='open').count()

    return render_template(
        'admin_dashboard.html',
        total_users=total_users,
        total_professionals=total_professionals,
        total_bookings=total_bookings,
        total_service_categories=total_service_categories,
        pending_bookings=pending_bookings,
        in_progress_bookings=in_progress_bookings,
        completed_bookings=completed_bookings,
        paid_bookings=paid_bookings,
        unpaid_bookings=unpaid_bookings,
        pending_verifications=pending_verifications,
        verified_professionals=verified_professionals,
        suspended_professionals=suspended_professionals,
        recent_bookings=recent_bookings,
        service_categories=service_categories,
        unverified_professionals=unverified_professionals,
        all_professionals=all_professionals,
        all_users=all_users,
        total_revenue=total_revenue,
        all_products=all_products,
        total_products=total_products,
        total_refunded_count=total_refunded_count,
        total_refunded_amount=total_refunded_amount,
        all_complaints=all_complaints,
        open_complaints_count=open_complaints_count
    )


# ── AJAX Search Endpoint ──────────────────────────────────────────────────
@app.route('/admin/search/')
def admin_search():
    if 'admin_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    query = request.args.get('q', '').strip()
    search_type = request.args.get('type', 'all')  # 'users', 'professionals', 'bookings', or 'all'

    results = {
        'users': [],
        'professionals': [],
        'bookings': []
    }

    if not query:
        return jsonify(results)

    like_pattern = f'%{query}%'

    # Search Users
    if search_type in ('all', 'users'):
        users = User.query.filter(
            db.or_(
                User.user_id.cast(db.String).like(like_pattern),
                User.first_name.like(like_pattern),
                User.last_name.like(like_pattern),
                User.email.like(like_pattern),
                User.phone_number.like(like_pattern),
                db.func.concat(User.first_name, ' ', User.last_name).like(like_pattern)
            )
        ).all()
        results['users'] = [{
            'id': u.user_id,
            'name': f'{u.first_name} {u.last_name}',
            'email': u.email,
            'phone': u.phone_number or 'N/A',
            'bookings_count': len(u.bookings)
        } for u in users]

    # Search Professionals
    if search_type in ('all', 'professionals'):
        professionals = Professional.query.filter(
            db.or_(
                Professional.professional_id.cast(db.String).like(like_pattern),
                Professional.first_name.like(like_pattern),
                Professional.last_name.like(like_pattern),
                Professional.email.like(like_pattern),
                Professional.business_name.like(like_pattern),
                Professional.phone_number.like(like_pattern),
                Professional.location.like(like_pattern),
                db.func.concat(Professional.first_name, ' ', Professional.last_name).like(like_pattern)
            )
        ).all()
        results['professionals'] = [{
            'id': p.professional_id,
            'name': f'{p.first_name} {p.last_name}',
            'business_name': p.business_name or 'N/A',
            'email': p.email,
            'phone': p.phone_number or 'N/A',
            'location': p.location or 'N/A',
            'status': p.account_status,
            'rating': float(p.average_rating or 0.0)
        } for p in professionals]

    # Search Bookings
    if search_type in ('all', 'bookings'):
        bookings = Booking.query.filter(
            db.or_(
                Booking.booking_id.cast(db.String).like(like_pattern),
                Booking.job_status.like(like_pattern),
                Booking.payment_status.like(like_pattern)
            )
        ).order_by(Booking.booking_id.desc()).all()
        results['bookings'] = [{
            'id': b.booking_id,
            'client_name': f'{b.user.first_name} {b.user.last_name}' if b.user else 'Unknown',
            'professional_name': f'{b.professional.first_name} {b.professional.last_name}' if b.professional else 'Unknown',
            'price': float(b.booking_price or 0.0),
            'job_status': b.job_status,
            'payment_status': b.payment_status,
            'scheduled_date': b.scheduled_date.strftime('%b %d, %Y') if b.scheduled_date else 'TBD'
        } for b in bookings]

    return jsonify(results)


# ── Verify Professional ───────────────────────────────────────────────────
@app.route('/admin/verify-professional/<int:professional_id>/', methods=['POST'])
def admin_verify_professional(professional_id):
    if 'admin_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    professional = db.session.get(Professional, professional_id)
    if not professional:
        return jsonify({'error': 'Professional not found'}), 404

    professional.account_status = 'verified'
    db.session.commit()
    
    try:
        send_verification_email(professional.email, professional.first_name)
    except Exception as e:
        print(f"Error sending verification email: {e}")
        
    return jsonify({'status': 'success', 'message': f'{professional.first_name} {professional.last_name} is now verified!'})


# ── Toggle Professional Suspension ───────────────────────────────────────
@app.route('/admin/suspend-professional/<int:professional_id>/', methods=['POST'])
def admin_suspend_professional(professional_id):
    if 'admin_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    # Find the professional
    professional = Professional.query.get(professional_id)
    if not professional:
        return jsonify({'error': 'Professional not found'}), 404

    # The dashboard now sends the action it intends to perform (based on the
    # status it last rendered). This makes the endpoint idempotent instead
    # of a blind toggle: asking to "suspend" an already-suspended account
    # (e.g. a duplicate/late click) is a no-op, not a re-flip back to verified.
    requested_action = request.form.get('action')
    if requested_action not in ('suspend', 'unsuspend'):
        # Fall back to legacy toggle behavior if no action was supplied.
        requested_action = 'unsuspend' if professional.account_status == 'suspended' else 'suspend'

    already_suspended = professional.account_status == 'suspended'

    if requested_action == 'suspend' and already_suspended:
        db.session.rollback()
        return jsonify({
            'status': 'success',
            'no_change': True,
            'account_status': 'suspended',
            'message': f'{professional.first_name} {professional.last_name} is already suspended.'
        })

    if requested_action == 'unsuspend' and not already_suspended:
        db.session.rollback()
        return jsonify({
            'status': 'success',
            'no_change': True,
            'account_status': professional.account_status,
            'message': f'{professional.first_name} {professional.last_name} is not currently suspended.'
        })

    new_status = 'suspended' if requested_action == 'suspend' else 'verified'
    professional.account_status = new_status
    db.session.commit()

    action = 'suspended' if new_status == 'suspended' else 'unsuspended'

    try:
        if new_status == 'suspended':
            send_suspension_email(professional.email, professional.first_name)
        else:
            send_unsuspension_email(professional.email, professional.first_name)
    except Exception as e:
        print(f"Error sending {action} email: {e}")

    return jsonify({
        'status': 'success',
        'no_change': False,
        'account_status': new_status,
        'message': f'{professional.first_name} {professional.last_name} has been {action}.'
    })


@app.route('/admin/financials/')
def admin_financials():
    if 'admin_id' not in session:
        flash('Please log in as admin first.', 'error')
        return redirect(url_for('admin_login'))

    period = request.args.get('period', 'all')
    now = datetime.datetime.now()

    if period == 'today':
        start_date = datetime.datetime.combine(now.date(), datetime.time.min)
    elif period == 'week':
        start_date = now - datetime.timedelta(days=now.weekday())
        start_date = datetime.datetime.combine(start_date.date(), datetime.time.min)
    elif period == 'month':
        start_date = datetime.datetime(now.year, now.month, 1)
    elif period == 'year':
        start_date = datetime.datetime(now.year, 1, 1)
    else:
        start_date = None

    query = Booking.query.filter(Booking.payment_status == 'paid')
    if start_date:
        query = query.filter(Booking.completion_date >= start_date if Booking.completion_date is not None else Booking.scheduled_date >= start_date)

    paid_bookings = query.all()
    total_gross_revenue = sum(float(b.booking_price or 0) for b in paid_bookings)
    transaction_count = len(paid_bookings)
    gateway_fee = sum((float(b.booking_price or 0) * 0.015) + 100 for b in paid_bookings)
    gateway_fee = min(gateway_fee, transaction_count * 2000)
    platform_fee = total_gross_revenue * 0.10
    professional_payouts = total_gross_revenue - platform_fee
    net_profit = platform_fee - gateway_fee

    pending_payouts = sum(float(b.booking_price or 0) * 0.90 for b in Booking.query.filter(
        Booking.job_status == 'completed', Booking.payment_status == 'paid'
    ).all())

    trend = []
    if paid_bookings:
        month_groups = {}
        for booking in paid_bookings:
            bucket = booking.completion_date or booking.scheduled_date or now
            key = bucket.strftime('%b %Y')
            month_groups[key] = month_groups.get(key, 0) + float(booking.booking_price or 0)
        trend = [
            {'label': label, 'value': value}
            for label, value in sorted(month_groups.items(), key=lambda item: item[0])
        ]

    return render_template(
        'admin_financials.html',
        period=period,
        total_gross_revenue=total_gross_revenue,
        platform_fee=platform_fee,
        professional_payouts=professional_payouts,
        gateway_fee=gateway_fee,
        net_profit=net_profit,
        pending_payouts=pending_payouts,
        transaction_count=transaction_count,
        trend=trend,
        paid_bookings=paid_bookings
    )


# ── Admin resolves or reopens a complaint ──────────────────────────────────
@app.route('/admin/complaint/<int:complaint_id>/update-status/', methods=['POST'])
def admin_update_complaint_status(complaint_id):
    if 'admin_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    complaint = Complaint.query.get(complaint_id)
    if not complaint:
        return jsonify({'status': 'error', 'message': 'Complaint not found'}), 404

    new_status = request.form.get('status', '')
    if new_status not in ['open', 'resolved', 'dismissed']:
        return jsonify({'status': 'error', 'message': 'Invalid status'}), 400

    complaint.status = new_status
    db.session.commit()

    # Notify the client by email about the status update
    if complaint.user:
        send_complaint_status_email(
            complaint.user.email,
            complaint.user.first_name,
            complaint.booking_id,
            complaint.subject,
            new_status
        )

    return jsonify({'status': 'success', 'message': f'Complaint marked as {new_status}.', 'new_status': new_status})


# ── Full detail view for one complaint: booking + professional track record ─
@app.route('/admin/complaint/<int:complaint_id>/details/')
def admin_complaint_details(complaint_id):
    if 'admin_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    complaint = Complaint.query.get(complaint_id)
    if not complaint:
        return jsonify({'status': 'error', 'message': 'Complaint not found'}), 404

    booking = complaint.booking
    professional = complaint.professional
    client = complaint.user

    # Professional's overall complaint track record (excluding this one)
    other_complaints_q = Complaint.query.filter(
        Complaint.professional_id == professional.professional_id,
        Complaint.complaint_id != complaint.complaint_id
    ).order_by(Complaint.created_at.desc())

    other_complaints = [
        {
            'complaint_id': c.complaint_id,
            'subject': c.subject,
            'message': c.message,
            'status': c.status,
            'created_at': c.created_at.strftime('%b %d, %Y') if c.created_at else None
        }
        for c in other_complaints_q.all()
    ]

    total_complaints = len(other_complaints) + 1
    open_count = sum(1 for c in other_complaints if c['status'] == 'open') + (1 if complaint.status == 'open' else 0)
    resolved_count = sum(1 for c in other_complaints if c['status'] == 'resolved') + (1 if complaint.status == 'resolved' else 0)

    return jsonify({
        'status': 'success',
        'complaint': {
            'complaint_id': complaint.complaint_id,
            'subject': complaint.subject,
            'message': complaint.message,
            'status': complaint.status,
            'created_at': complaint.created_at.strftime('%b %d, %Y %I:%M %p') if complaint.created_at else None
        },
        'booking': {
            'booking_id': booking.booking_id if booking else None,
            'scheduled_date': booking.scheduled_date.strftime('%A, %b %d, %Y') if booking and booking.scheduled_date else 'N/A',
            'booking_price': float(booking.booking_price) if booking and booking.booking_price else 0,
            'address': booking.address if booking else 'N/A',
            'job_status': booking.job_status if booking else 'N/A',
            'payment_status': booking.payment_status if booking else 'N/A'
        },
        'client': {
            'name': f"{client.first_name} {client.last_name}".strip() if client else 'Unknown',
            'email': client.email if client else 'N/A'
        },
        'professional': {
            'professional_id': professional.professional_id if professional else None,
            'name': f"{professional.first_name} {professional.last_name}".strip() if professional else 'Unknown',
            'business_name': professional.business_name if professional else None,
            'account_status': professional.account_status if professional else 'N/A',
            'average_rating': float(professional.average_rating) if professional and professional.average_rating else 0,
            'date_joined': professional.date_joined.strftime('%b %Y') if professional and professional.date_joined else 'N/A'
        },
        'track_record': {
            'total_complaints': total_complaints,
            'open_count': open_count,
            'resolved_count': resolved_count
        },
        'other_complaints': other_complaints
    })


# ── Delete Booking ────────────────────────────────────────────────────────
@app.route('/admin/delete-booking/<int:booking_id>/', methods=['POST'])
def admin_delete_booking(booking_id):
    if 'admin_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    booking = db.session.get(Booking, booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404

    db.session.delete(booking)
    db.session.commit()
    return jsonify({'status': 'success', 'message': f'Booking #{booking_id} has been deleted.'})


# ── Add Service Category ──────────────────────────────────────────────────
@app.route('/admin/add-category/', methods=['POST'])
def admin_add_category():
    if 'admin_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Category name is required'}), 400

    existing = ServiceCategory.query.filter(
        db.func.lower(ServiceCategory.service_category_name) == name.lower()
    ).first()
    if existing:
        return jsonify({'error': 'Category already exists'}), 400

    category = ServiceCategory(service_category_name=name)
    db.session.add(category)
    db.session.commit()
    return jsonify({'status': 'success', 'message': f'Category "{name}" added!', 'id': category.service_category_id})


# ── Delete Service Category ──────────────────────────────────────────────
@app.route('/admin/delete-category/<int:category_id>/', methods=['POST'])
def admin_delete_category(category_id):
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    category = db.session.get(ServiceCategory, category_id)
    if not category:
        flash('Category not found.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    if category.professional_services:
        return jsonify({
            'error': f'Cannot delete "{category.service_category_name}": '
                     f'{len(category.professional_services)} professional service(s) '
                     f'still use this category (deleting it would also delete their '
                     f'bookings and reviews). Reassign or remove those services first.'
        }), 400

    db.session.delete(category)
    db.session.commit()
    return jsonify({'status': 'success', 'message': f'Category "{category.service_category_name}" deleted.'})


# ── Edit/Delete Users & Professionals ──────────────────────────────────────────────
@app.route('/admin/edit-user/<int:user_id>/', methods=['POST'])
def admin_edit_user(user_id):
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    user.first_name = request.form.get('first_name', user.first_name)
    user.last_name = request.form.get('last_name', user.last_name)
    user.email = request.form.get('email', user.email)
    user.phone_number = request.form.get('phone_number', user.phone_number)
    
    db.session.commit()
    flash(f"User {user.first_name} {user.last_name} updated successfully.", 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/edit-professional/<int:professional_id>/', methods=['POST'])
def admin_edit_professional(professional_id):
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    prof = db.session.get(Professional, professional_id)
    if not prof:
        flash('Professional not found.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    prof.first_name = request.form.get('first_name', prof.first_name)
    prof.last_name = request.form.get('last_name', prof.last_name)
    prof.business_name = request.form.get('business_name', prof.business_name)
    prof.email = request.form.get('email', prof.email)
    prof.phone_number = request.form.get('phone_number', prof.phone_number)
    old_status = prof.account_status
    prof.account_status = request.form.get('account_status', prof.account_status)
    
    db.session.commit()
    
    if old_status != 'verified' and prof.account_status == 'verified':
        try:
            send_verification_email(prof.email, prof.first_name)
        except Exception as e:
            print(f"Error sending verification email: {e}")
            
    flash(f"Professional {prof.first_name} {prof.last_name} updated successfully.", 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete-user/<int:user_id>/', methods=['POST'])
def admin_delete_user(user_id):
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    user = db.session.get(User, user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully.', 'success')
    
    return redirect(url_for('admin_dashboard'))


# ── Generate Admin Seed (one-time use in dev) ─────────────────────────────
@app.route('/admin/seed/', methods=['POST'])
def admin_seed():
    # This route previously had no auth at all, so anyone on the internet
    # could (re)create the well-known admin@kiraar.com / admin123 account
    # any time no admin row existed. It now requires a secret set via the
    # ADMIN_SEED_SECRET environment variable, passed as ?secret=... or the
    # X-Seed-Secret header. If the env var isn't set, the route is disabled
    # entirely — set it only temporarily for the initial seed, then unset it.
    configured_secret = os.environ.get('ADMIN_SEED_SECRET')
    if not configured_secret:
        return jsonify({'error': 'Seeding is disabled'}), 403

    provided_secret = request.headers.get('X-Seed-Secret') or request.args.get('secret', '')
    if not secrets.compare_digest(provided_secret, configured_secret):
        return jsonify({'error': 'Seeding is disabled'}), 403

    # Only allow if no admin exists yet
    if Admin.query.first():
        return jsonify({'error': 'Admin already exists'}), 400

    seed_email = os.environ.get('ADMIN_SEED_EMAIL', 'admin@kiraar.com')
    seed_password = os.environ.get('ADMIN_SEED_PASSWORD') or secrets.token_urlsafe(12)

    admin = Admin(
        email=seed_email.lower(),
        password=generate_password_hash(seed_password)
    )
    db.session.add(admin)
    db.session.commit()

    message = f'Admin created! Email: {seed_email}'
    # Only echo the password back if it was auto-generated (not set via env var),
    # since a caller-supplied password is already known to them.
    if not os.environ.get('ADMIN_SEED_PASSWORD'):
        message += f' / Password: {seed_password}'
    return jsonify({'status': 'success', 'message': message})

@app.route('/admin/delete_product/<int:product_id>', methods=['POST'])
def admin_delete_product(product_id):
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    product = Product.query.get_or_404(product_id)
    
    if product.product_image:
        import os
        try:
            os.remove(os.path.join(app.root_path, 'static', 'uploads', product.product_image))
        except:
            pass
            
    db.session.delete(product)
    db.session.commit()
    flash('Product/Job deleted successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

