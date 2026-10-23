from pkg import app
from pkg.models import db, ServiceCategory

# This file is used by Gunicorn (production server) to serve the app.
# Render runs: gunicorn wsgi:app

# Automatically create tables and seed default categories on startup
with app.app_context():
    try:
        db.create_all()
        if ServiceCategory.query.count() == 0:
            default_categories = [
                'Plumber', 'Electrician', 'Carpenter', 'Cleaner', 'Painter', 'Mechanic',
                'Welder', 'Tailor', 'Barber', 'Hair Stylist', 'Makeup Artist', 'Gardener',
                'Mason', 'Tiler', 'Roofer', 'Laundry', 'Chef', 'Caterer', 'Event Planner',
                'Photographer', 'Videographer', 'DJ', 'MC', 'Bricklayer', 'POP Ceiling Installer',
                'Fumigator', 'Pest Control', 'AC Technician', 'Fridge Repair', 'Generator Repair',
                'Laptop Repair', 'Phone Repair', 'TV Repair', 'Satellite Installer', 'CCTV Installer',
                'Solar Panel Installer', 'Furniture Maker', 'Upholsterer', 'Shoe Maker', 'Baker',
                'House Cleaner', 'Deep Cleaner', 'Locksmith', 'Gate Fabricator', 'Borehole Driller',
                'Car Wash', 'Auto Electrician', 'Panel Beater', 'Auto Painter'
            ]
            for cat_name in default_categories:
                db.session.add(ServiceCategory(service_category_name=cat_name))
            db.session.commit()
    except Exception as e:
        app.logger.error(f"Startup database initialization: {e}")
