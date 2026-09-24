from flask import Flask
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

from datetime import timedelta
from pkg.config import LiveConfig

csrf = CSRFProtect()

def create_app():
    
    from pkg.models import db

    app = Flask(__name__, instance_relative_config=False)
    app.config.from_pyfile('config.py')
    app.config.from_object(LiveConfig)

    # Set session lifetime to 7 days so the admin dashboard doesn't log out quickly
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

    db.init_app(app)
    migrate = Migrate(app,db)
    csrf.init_app(app)

    return app

app = create_app()

from pkg import user_routes, admin_routes,forms

# ==========================================
# AUTO-RELEASE SCHEDULER (2-day escrow payout)
# ==========================================
from apscheduler.schedulers.background import BackgroundScheduler
import datetime
import json


def auto_release_payments():
    """Check for bookings completed 2+ days ago that haven't been paid out,
    and release payment automatically via the same Paystack transfer path
    used by the manual 'release payment' button.
    """
    with app.app_context():
        from pkg.models import db, Booking, Payout
        from pkg.user_routes import payoutFromEscrow, send_payout_email

        cutoff = datetime.datetime.now() - datetime.timedelta(days=2)
        eligible = Booking.query.filter(
            Booking.job_status == 'completed',
            Booking.is_paid_out == False,
            Booking.completion_date.isnot(None),
            Booking.completion_date <= cutoff,
            Booking.payment_status == 'paid',
            Booking.is_refunded == False
        ).all()

        app.logger.info(f"Auto-release: found {len(eligible)} eligible booking(s)")

        for booking in eligible:
            professional = booking.professional
            if not professional or not professional.recipient_code:
                app.logger.warning(
                    f"Booking {booking.booking_id}: no recipient_code, skipping auto-release"
                )
                continue

            try:
                amt = float(booking.booking_price or 0.0)
                pro_amount = round(amt * 0.90, 2)
                amount_kobo = int(pro_amount * 100)

                status_code, data = payoutFromEscrow(professional.professional_id, amount_kobo)

                if status_code in (200, 201) and data.get('status'):
                    ref = (
                        data.get('data', {}).get('reference')
                        or data.get('data', {}).get('transfer_code')
                        or str(data.get('data', {}))
                    )
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
                    app.logger.info(f"Auto-released payout for booking {booking.booking_id}")

                    # Send payout email to artisan
                    send_payout_email(
                        professional.email,
                        f"{professional.first_name} {professional.last_name}",
                        pro_amount,
                        booking.booking_id,
                        professional.bank_name,
                        professional.account_number,
                        ref
                    )
                else:
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
                    app.logger.error(
                        f"Auto-release failed for booking {booking.booking_id}: {data}"
                    )
            except Exception:
                db.session.rollback()
                app.logger.exception(f"Exception auto-releasing booking {booking.booking_id}")


# NOTE: if you run multiple worker processes (e.g. gunicorn -w 4), each
# process will start its own scheduler and you'll get duplicate release
# attempts per booking. Run with a single worker, or add a DB-level lock
# in auto_release_payments before scaling out.
_scheduler = BackgroundScheduler(daemon=True)
_scheduler.add_job(
    func=auto_release_payments,
    trigger='interval',
    hours=1,
    id='auto_release_payments',
    replace_existing=True
)
_scheduler.start()