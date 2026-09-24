from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone


db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'user'

    user_id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(255), nullable=False)
    last_name = db.Column(db.String(225), nullable=False)
    email = db.Column(db.String(225), unique=True, nullable=False)
    password = db.Column(db.String(225), nullable=False)
    phone_number = db.Column(db.String(225))

    bookings = db.relationship('Booking', back_populates='user', cascade='all, delete-orphan')
    reviews = db.relationship('Review', back_populates='user', cascade='all, delete-orphan')
    complaints = db.relationship('Complaint', back_populates='user', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.first_name} {self.last_name}>'


class Professional(db.Model):
    __tablename__ = 'professional'

    professional_id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(225), nullable=False)
    last_name = db.Column(db.String(225), nullable=False)
    email = db.Column(db.String(225), unique=True, nullable=False)
    password = db.Column(db.String(225), nullable=False)
    phone_number = db.Column(db.String(225))
    business_name = db.Column(db.String(225))
    bio = db.Column(db.String(225))
    profile_picture = db.Column(db.String(225))
    business_type = db.Column(db.String(225))
    location = db.Column(db.String(225))
    date_joined = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(225))
    account_status = db.Column(
        db.Enum('pending', 'verified', 'suspended', name='account_status_enum'),
        default='pending'
    )
    average_rating = db.Column(db.Numeric(2, 1), default=0.0)
    show_first_name = db.Column(db.Boolean, default=True)
    show_last_name = db.Column(db.Boolean, default=True)
    show_business_name = db.Column(db.Boolean, default=True)
    bank_name = db.Column(db.String(225))
    bank_code = db.Column(db.String(10))
    account_number = db.Column(db.String(20))
    account_name = db.Column(db.String(225))
    recipient_code = db.Column(db.String(100))

    # A professional can receive many bookings, offer many services, and sell many products.
    bookings = db.relationship('Booking', back_populates='professional', cascade='all, delete-orphan')
    professional_services = db.relationship('ProfessionalService', back_populates='professional', cascade='all, delete-orphan')
    products = db.relationship('Product', back_populates='professional', cascade='all, delete-orphan')
    reviews = db.relationship('Review', back_populates='professional', cascade='all, delete-orphan')
    complaints = db.relationship('Complaint', back_populates='professional', cascade='all, delete-orphan')


    def __repr__(self):
        return f'<Professional {self.business_name or self.first_name}>'


class ServiceCategory(db.Model):
    __tablename__ = 'service_category'

    service_category_id = db.Column(db.Integer, primary_key=True)
    service_category_name = db.Column(db.String(225), nullable=False)

    # One service category can be used by many professional services.
    professional_services = db.relationship('ProfessionalService', back_populates='service_category', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ServiceCategory {self.service_category_name}>'


class ProfessionalService(db.Model):
    __tablename__ = 'professional_service'

    professional_service_id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.professional_id'), nullable=False)
    service_category_id = db.Column(db.Integer, db.ForeignKey('service_category.service_category_id'), nullable=False)
    rate = db.Column(db.Numeric(15, 2), nullable=False)

    # A service belongs to one professional and one service category, and can appear in many bookings.
    professional = db.relationship('Professional', back_populates='professional_services')
    service_category = db.relationship('ServiceCategory', back_populates='professional_services')
    bookings = db.relationship('Booking', back_populates='professional_service', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ProfessionalService {self.professional_service_id}>'


class Booking(db.Model):
    __tablename__ = 'booking'

    booking_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.professional_id'), nullable=False)
    professional_service_id = db.Column(
        db.Integer, db.ForeignKey('professional_service.professional_service_id'), nullable=False
    )
    scheduled_date = db.Column(db.DateTime, nullable=False)
    job_status = db.Column(
        db.Enum('pending', 'in-progress', 'completed', name='job_status_enum'),
        default='pending'
    )
    booking_price = db.Column(db.Numeric(15, 2), nullable=False)
    completion_date = db.Column(db.DateTime)
    address = db.Column(db.String(225))
    payment_status = db.Column(
        db.Enum('unpaid', 'paid', name='payment_status_enum'),
        default='unpaid'
    )
    payment_reference = db.Column(db.String(255))
    is_refunded = db.Column(db.Boolean, default=False)
    is_paid_out = db.Column(db.Boolean, default=False)
    payout_reference = db.Column(db.String(255))
    price_updated = db.Column(db.Boolean, default=False)
    price_updated_by = db.Column(db.String(50), default=None)  # 'professional' or 'client'

    # A booking links a user, a professional, and one service together.
    user = db.relationship('User', back_populates='bookings')
    professional = db.relationship('Professional', back_populates='bookings')
    professional_service = db.relationship('ProfessionalService', back_populates='bookings')
    review = db.relationship('Review', back_populates='booking', uselist=False, cascade='all, delete-orphan')
    complaints = db.relationship('Complaint', back_populates='booking', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Booking {self.booking_id}>'

class Review(db.Model):
    __tablename__ = 'review'

    review_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.professional_id'), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.booking_id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    review_text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship('User', back_populates='reviews')
    professional = db.relationship('Professional', back_populates='reviews')
    booking = db.relationship('Booking', back_populates='review')

    def __repr__(self):
        return f'<Review {self.review_id} rating={self.rating}>'


class Complaint(db.Model):
    __tablename__ = 'complaint'

    complaint_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.professional_id'), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.booking_id'), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='open')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', back_populates='complaints')
    professional = db.relationship('Professional', back_populates='complaints')
    booking = db.relationship('Booking', back_populates='complaints')

    def __repr__(self):
        return f'<Complaint {self.complaint_id}>'


class Admin(db.Model):
    __tablename__ = 'admin'

    admin_id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(225), unique=True, nullable=False)
    password = db.Column(db.String(225), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Admin {self.email}>'


class Product(db.Model):
    __tablename__ = 'product'

    product_id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.professional_id'), nullable=False)
    product_name = db.Column(db.String(225), nullable=False)
    description = db.Column(db.String(225))
    price = db.Column(db.Numeric(12, 2), nullable=False)
    product_image = db.Column(db.String(225))

    professional = db.relationship('Professional', back_populates='products')

    def __repr__(self):
        return f'<Product {self.product_name}>'


class Payout(db.Model):
    __tablename__ = 'payout'

    payout_id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.booking_id'), nullable=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.professional_id'), nullable=True)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    currency = db.Column(db.String(10), default='NGN')
    status = db.Column(db.String(50), default='pending')
    reference = db.Column(db.String(255))
    response = db.Column(db.Text)  # store raw JSON response from Paystack
    attempts = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Payout {self.payout_id} ref={self.reference} status={self.status}>'



