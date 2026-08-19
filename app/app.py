import os
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
import shutil
import subprocess
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_bcrypt import Bcrypt
import jwt
import json
from sqlalchemy import text
from uuid import uuid4
# Rate limiter removed per user request; provide a noop limiter decorator
class _NoopLimiter:
    def limit(self, *args, **kwargs):
        def _decorator(f):
            return f
        return _decorator

limiter = _NoopLimiter()
from cryptography.fernet import Fernet
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'library-system-pro-secret-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///library.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET'] = os.environ.get('JWT_SECRET', app.config['SECRET_KEY'])
app.config['JWT_ALGORITHM'] = 'HS256'
app.config['JWT_EXP_DELTA_SECONDS'] = int(os.environ.get('JWT_EXP_DELTA_SECONDS', 3600))
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
app.config['SESSION_COOKIE_SAMESITE'] = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
app.config['PREFERRED_URL_SCHEME'] = 'https'
# SQLAlchemy engine pooling options (tune via env)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': int(os.environ.get('DB_POOL_SIZE', 20)),
    'max_overflow': int(os.environ.get('DB_MAX_OVERFLOW', 10)),
    'pool_pre_ping': True,
}

db = SQLAlchemy(app)
migrate = Migrate(app, db)
bcrypt = Bcrypt(app)

# Redis removed; use DB-only storage for token revocation and refresh tokens
cache_redis = None

@app.context_processor
def inject_globals():
    return {'has_logo': os.path.exists(os.path.join(app.static_folder, 'uswa-logo.png'))}

LOW_STOCK_THRESHOLD = 2

class User(db.Model):
    __tablename__ = 'librarians'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(150))
    role = db.Column(db.String(50), default='LIBRARIAN')
    recovery_answer = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        try:
            return bcrypt.check_password_hash(self.password_hash, password)
        except Exception:
            return False

class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    accession_number = db.Column(db.String(100), unique=True, nullable=True)
    isbn = db.Column(db.String(20), unique=True, nullable=True)
    title = db.Column(db.String(255), nullable=False)
    author = db.Column(db.String(150), nullable=False)
    publisher = db.Column(db.String(150), nullable=True)
    category = db.Column(db.String(100), nullable=True)
    publication_year = db.Column(db.Integer, nullable=True)
    purchase_price = db.Column(db.Float, default=0.0)
    quantity = db.Column(db.Integer, default=1)
    available_copies = db.Column(db.Integer, default=1)
    shelf_location = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(50), default='AVAILABLE')
    description = db.Column(db.Text)
    summary = db.Column(db.Text)
    tags = db.Column(db.String(500))
    embedding_json = db.Column(db.Text)  # store embedding as JSON array
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    issued_records = db.relationship('IssuedRecord', backref='book', lazy=True, cascade='all, delete-orphan')
    borrow_history = db.relationship('BorrowHistory', backref='book', lazy=True, cascade='all, delete-orphan')

    @property
    def is_low_stock(self):
        return self.available_copies <= LOW_STOCK_THRESHOLD and self.available_copies > 0

    @property
    def is_out_of_stock(self):
        return self.available_copies == 0

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    class_name = db.Column(db.String(50))
    section = db.Column(db.String(20))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    borrowing_history = db.relationship('BorrowHistory', backref='student', lazy=True, cascade='all, delete-orphan')
    fine_history = db.relationship('StudentFineReport', backref='student', lazy=True, cascade='all, delete-orphan')
    enrollment_year = db.Column(db.Integer, default=datetime.now().year)
    address = db.Column(db.Text)
    fine_balance = db.Column(db.Float, default=0.0)
    total_fines_paid = db.Column(db.Float, default=0.0)
    books_borrowed = db.Column(db.Integer, default=0)
    books_returned = db.Column(db.Integer, default=0)
    books_overdue = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    issued_records = db.relationship('IssuedRecord', backref='student', lazy=True, cascade='all, delete-orphan')

class IssuedRecord(db.Model):
    __tablename__ = 'issues'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    issue_date = db.Column(db.DateTime, default=datetime.now)
    due_date = db.Column(db.DateTime, nullable=False)
    returned_date = db.Column(db.DateTime)
    is_returned = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)

    @property
    def is_overdue(self):
        return not self.is_returned and datetime.now() > self.due_date

    @property
    def days_overdue(self):
        if self.is_returned:
            return 0 if self.returned_date <= self.due_date else (self.returned_date - self.due_date).days
        return (datetime.now() - self.due_date).days if self.is_overdue else 0

    @property
    def fine_amount(self):
        return max(0, self.days_overdue * 5)

class BorrowHistory(db.Model):
    __tablename__ = 'book_copies'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    issue_date = db.Column(db.DateTime, nullable=False)
    due_date = db.Column(db.DateTime, nullable=False)
    returned_date = db.Column(db.DateTime)
    status = db.Column(db.String(50))
    fine_paid = db.Column(db.Float, default=0.0)

class StudentFineReport(db.Model):
    __tablename__ = 'fines'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    payment_status = db.Column(db.String(50), default='PENDING')
    issued_date = db.Column(db.DateTime, default=datetime.now)
    paid_date = db.Column(db.DateTime)

class ActivityLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('librarians.id'))
    action = db.Column(db.String(255), nullable=False)
    entity_type = db.Column(db.String(50))
    entity_id = db.Column(db.Integer)
    description = db.Column(db.Text)
    ip_address = db.Column(db.String(100))
    user_agent = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.now)

class StudentNote(db.Model):
    __tablename__ = 'student_notes'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('librarians.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    user = db.relationship('User', backref='notes')

class StudentWishlist(db.Model):
    __tablename__ = 'student_wishlist'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    added_by = db.Column(db.Integer, db.ForeignKey('librarians.id'), nullable=False)
    note = db.Column(db.String(255))
    added_at = db.Column(db.DateTime, default=datetime.now)
    book = db.relationship('Book', backref='wishlisted_by')
    added_by_user = db.relationship('User', backref='wishlist_additions')


class Backup(db.Model):
    __tablename__ = 'backups'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    storage = db.Column(db.String(50), default='local')
    size = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)


class RevokedToken(db.Model):
    __tablename__ = 'revoked_tokens'
    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('librarians.id'))
    revoked_at = db.Column(db.DateTime, default=datetime.now)


class RefreshToken(db.Model):
    __tablename__ = 'refresh_tokens'
    token = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('librarians.id'))
    expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'danger')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'ADMIN':
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            log_activity(user.id, 'LOGIN', 'User', user.id, f'User {username} logged in')
            flash(f'Welcome back, {user.full_name or username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')


def generate_jwt(user_id):
    jti = str(uuid4())
    iat = datetime.utcnow()
    exp = iat + timedelta(seconds=app.config.get('JWT_EXP_DELTA_SECONDS', 3600))
    payload = {
        'user_id': user_id,
        'jti': jti,
        'iat': iat,
        'exp': exp
    }
    token = jwt.encode(payload, app.config['JWT_SECRET'], algorithm=app.config['JWT_ALGORITHM'])
    return token


def decode_jwt(token):
    try:
        data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=[app.config['JWT_ALGORITHM']])
        # check token revocation (Redis first for speed, then DB)
        jti = data.get('jti')
        if jti:
            try:
                # Redis removed; check DB only
                pass
            except Exception:
                pass
            try:
                revoked = RevokedToken.query.filter_by(jti=jti).first()
                if revoked:
                    return None
            except Exception:
                pass
        return data
    except Exception:
        return None


def revoke_jti(jti, user_id=None, ttl=None):
    try:
        if ttl is None:
            ttl = app.config.get('JWT_EXP_DELTA_SECONDS', 3600)
        # store in DB
        if not RevokedToken.query.filter_by(jti=jti).first():
            rt = RevokedToken(jti=jti, user_id=user_id)
            db.session.add(rt)
            db.session.commit()
        # Redis removed; DB-only revocation
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def revoke_refresh_token(refresh_token):
    try:
        # delete from DB-backed refresh tokens
        rt = RefreshToken.query.filter_by(token=refresh_token).first()
        if rt:
            db.session.delete(rt)
            db.session.commit()
    except Exception:
        pass


def jwt_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', None)
        if not auth or not auth.startswith('Bearer '):
            return jsonify({'error': 'Authorization header missing'}), 401
        token = auth.split(' ', 1)[1]
        data = decode_jwt(token)
        if not data:
            return jsonify({'error': 'Invalid or expired token'}), 401
        request.jwt_user = User.query.get(data.get('user_id'))
        return f(*args, **kwargs)
    return decorated


@app.route('/api/login', methods=['POST'])
@limiter.limit('6 per minute')
def api_login():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    user = User.query.filter_by(username=username, is_active=True).first()
    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid credentials'}), 401
    access_token = generate_jwt(user.id)
    # create a DB-backed refresh token
    refresh_token = str(uuid4())
    refresh_ttl = int(os.environ.get('REFRESH_TOKEN_EXPIRES', 7 * 24 * 3600))
    try:
        rt = RefreshToken(token=refresh_token, user_id=user.id, expires_at=datetime.utcnow() + timedelta(seconds=refresh_ttl))
        db.session.add(rt)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    log_activity(user.id, 'API_LOGIN', 'User', user.id, f'User {username} authenticated via API')
    return jsonify({'access_token': access_token, 'refresh_token': refresh_token,
                    'user': {'id': user.id, 'username': user.username, 'role': user.role}})


@app.route('/api/logout', methods=['POST'])
@jwt_required
def api_logout():
    auth = request.headers.get('Authorization', '')
    token = auth.split(' ', 1)[1] if ' ' in auth else auth
    data = decode_jwt(token)
    if not data:
        return jsonify({'error': 'Invalid token'}), 400
    jti = data.get('jti')
    try:
        revoke_jti(jti, user_id=data.get('user_id'))
        # also revoke refresh token if provided in body
        try:
            body = request.get_json() or {}
            rtoken = body.get('refresh_token')
            if rtoken:
                revoke_refresh_token(rtoken)
        except Exception:
            pass
        log_activity(data.get('user_id'), 'API_LOGOUT', 'User', data.get('user_id'), 'User logged out via API')
    except Exception:
        db.session.rollback()
    return jsonify({'success': True, 'message': 'Logged out'}), 200


@app.route('/api/refresh', methods=['POST'])
@limiter.limit('10 per minute')
def api_refresh():
    data = request.get_json() or {}
    refresh_token = data.get('refresh_token')
    if not refresh_token:
        return jsonify({'error': 'Refresh token required'}), 400
    try:
        rt = RefreshToken.query.filter_by(token=refresh_token).first()
        if rt and rt.expires_at and rt.expires_at > datetime.utcnow():
            # rotate token
            user_id = rt.user_id
            try:
                db.session.delete(rt)
                db.session.commit()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
            new_refresh = str(uuid4())
            refresh_ttl = int(os.environ.get('REFRESH_TOKEN_EXPIRES', 7 * 24 * 3600))
            try:
                new_rt = RefreshToken(token=new_refresh, user_id=user_id, expires_at=datetime.utcnow() + timedelta(seconds=refresh_ttl))
                db.session.add(new_rt)
                db.session.commit()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
            access_token = generate_jwt(int(user_id))
            return jsonify({'access_token': access_token, 'refresh_token': new_refresh}), 200
    except Exception:
        pass
    return jsonify({'error': 'Invalid refresh token'}), 401


@app.route('/logout')
def logout():
    if 'user_id' in session:
        log_activity(session['user_id'], 'LOGOUT', 'User', session['user_id'], 'User logged out')
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/password-recovery', methods=['GET', 'POST'])
def password_recovery():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        recovery_answer = request.form.get('recovery_answer', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        user = User.query.filter_by(username=username).first()
        if not user:
            flash('Username not found.', 'danger')
        elif new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
        elif len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
        elif user.recovery_answer and bcrypt.check_password_hash(user.recovery_answer, recovery_answer):
            user.set_password(new_password)
            db.session.commit()
            flash('Password reset successfully. Please log in.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Recovery answer is incorrect.', 'danger')
    return render_template('password_recovery.html')


@app.route('/dashboard')
@login_required
def dashboard():
    total_books = Book.query.count()
    total_students = Student.query.count()
    issued_count = IssuedRecord.query.filter_by(is_returned=False).count()
    overdue_count = IssuedRecord.query.filter(
        IssuedRecord.is_returned == False,
        IssuedRecord.due_date < datetime.now()
    ).count()
    total_fines = db.session.query(db.func.sum(StudentFineReport.amount)).filter_by(
        payment_status='PENDING').scalar() or 0.0
    recent_issues = IssuedRecord.query.order_by(IssuedRecord.issue_date.desc()).limit(5).all()

    low_stock_books = Book.query.filter(
        Book.available_copies <= LOW_STOCK_THRESHOLD,
        Book.status == 'AVAILABLE'
    ).order_by(Book.available_copies.asc()).limit(10).all()

    months_labels = []
    months_data = []
    for i in range(5, -1, -1):
        dt = datetime.now() - timedelta(days=30 * i)
        label = dt.strftime('%b %Y')
        months_labels.append(label)
        count = BorrowHistory.query.filter(
            db.extract('month', BorrowHistory.issue_date) == dt.month,
            db.extract('year', BorrowHistory.issue_date) == dt.year
        ).count()
        months_data.append(count)

    cat_data = db.session.query(Book.category, db.func.count(Book.id))\
        .filter(Book.category != None, Book.category != '')\
        .group_by(Book.category)\
        .order_by(db.func.count(Book.id).desc())\
        .limit(6).all()
    cat_labels = [c[0] for c in cat_data]
    cat_counts = [c[1] for c in cat_data]

    return render_template('dashboard.html',
        total_books=total_books,
        total_students=total_students,
        issued_count=issued_count,
        overdue_count=overdue_count,
        total_fines=total_fines,
        recent_issues=recent_issues,
        low_stock_books=low_stock_books,
        months_labels=months_labels,
        months_data=months_data,
        cat_labels=cat_labels,
        cat_counts=cat_counts,
        LOW_STOCK_THRESHOLD=LOW_STOCK_THRESHOLD
    )


@app.route('/api/search')
@login_required
def api_search():
    q = request.args.get('q', '').strip()
    kind = request.args.get('kind', 'all')
    if len(q) < 2:
        return jsonify({'books': [], 'students': []})

    cache_key = f"search:{kind}:{q.lower()}"
    # Try Redis cache first
    if cache_redis:
        try:
            cached = cache_redis.get(cache_key)
            if cached:
                return jsonify(json.loads(cached))
        except Exception:
            pass

    results = {'books': [], 'students': []}

    if kind in ('books', 'all'):
        books = Book.query.filter(
            db.or_(
                Book.title.ilike(f'%{q}%'),
                Book.author.ilike(f'%{q}%'),
                Book.isbn.ilike(f'%{q}%')
            )
        ).limit(6).all()
        results['books'] = [
            {'id': b.id, 'title': b.title, 'author': b.author,
             'available': b.available_copies, 'low_stock': b.is_low_stock,
             'out_of_stock': b.is_out_of_stock}
            for b in books
        ]

    if kind in ('students', 'all'):
        students = Student.query.filter(
            db.or_(
                Student.full_name.ilike(f'%{q}%'),
                Student.student_id.ilike(f'%{q}%')
            )
        ).limit(6).all()
        results['students'] = [
            {'id': s.id, 'name': s.full_name, 'student_id': s.student_id,
             'class_name': s.class_name or ''}
            for s in students
        ]

    # Redis removed — no search caching

    return jsonify(results)


@app.route('/books')
@login_required
def books_list():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    stock_filter = request.args.get('stock', '').strip()

    query = Book.query
    if search:
        query = query.filter(db.or_(
            Book.title.ilike(f'%{search}%'),
            Book.author.ilike(f'%{search}%'),
            Book.isbn.ilike(f'%{search}%'),
            Book.accession_number.ilike(f'%{search}%')
        ))
    if category:
        query = query.filter_by(category=category)
    if stock_filter == 'low':
        query = query.filter(Book.available_copies <= LOW_STOCK_THRESHOLD)
    elif stock_filter == 'out':
        query = query.filter(Book.available_copies == 0)

    books = query.paginate(page=page, per_page=20)
    categories = db.session.query(Book.category).distinct().all()

    return render_template('books.html', books=books, categories=categories,
                           search=search, category=category, stock_filter=stock_filter,
                           LOW_STOCK_THRESHOLD=LOW_STOCK_THRESHOLD)


@app.route('/admin/books/<int:book_id>/enrich', methods=['POST'])
@admin_required
def enrich_book(book_id):
    from services.gemini_service import generate_summary_and_tags, generate_embedding
    book = Book.query.get_or_404(book_id)
    try:
        out = generate_summary_and_tags(book.title, book.author, book.description or '')
        # attempt to parse JSON from model output
        import json as _json
        try:
            parsed = _json.loads(out)
            summary = parsed.get('summary') or parsed.get('Summary') or ''
            tags = parsed.get('tags') or parsed.get('Tags') or []
        except Exception:
            # fallback: store raw output as summary
            summary = out
            tags = []
        emb_json = None
        try:
            emb_json = generate_embedding((book.title or '') + '\n' + (book.description or ''))
        except Exception:
            emb_json = None
        book.summary = summary
        book.tags = ','.join(tags) if isinstance(tags, (list, tuple)) else (tags or '')
        if emb_json:
            book.embedding_json = emb_json
        db.session.commit()
        flash('Book enriched successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Enrichment failed: {str(e)}', 'danger')
    return redirect(url_for('books_list'))


@app.route('/admin/books/enrich_batch', methods=['POST'])
@admin_required
def enrich_batch():
    from services.gemini_service import generate_summary_and_tags, generate_embedding
    limit = int(request.form.get('limit', 100))
    last_id = int(request.form.get('last_id', 0))
    try:
        books = Book.query.filter(Book.id > last_id).order_by(Book.id).limit(limit).all()
        for b in books:
            try:
                out = generate_summary_and_tags(b.title, b.author, b.description or '')
                import json as _json
                try:
                    parsed = _json.loads(out)
                    summary = parsed.get('summary') or parsed.get('Summary') or ''
                    tags = parsed.get('tags') or parsed.get('Tags') or []
                except Exception:
                    summary = out
                    tags = []
                b.summary = summary
                b.tags = ','.join(tags) if isinstance(tags, (list, tuple)) else (tags or '')
                try:
                    emb = generate_embedding((b.title or '') + '\n' + (b.description or ''))
                    b.embedding_json = emb
                except Exception:
                    pass
                db.session.commit()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
        flash(f'Batch enrichment completed ({len(books)} books).', 'success')
    except Exception as e:
        flash(f'Batch enrichment failed: {str(e)}', 'danger')
    return redirect(url_for('books_list'))


@app.route('/books/add', methods=['GET', 'POST'])
@login_required
def add_book():
    if request.method == 'POST':
        try:
            accession = request.form.get('accession_number', '').strip() or None
            isbn = request.form.get('isbn', '').strip() or None
            title = request.form.get('title').strip()
            author = request.form.get('author').strip()
            publisher = request.form.get('publisher', '').strip() or None
            category = request.form.get('category', '').strip() or None
            publication_year = int(request.form.get('publication_year', 0)) or None
            purchase_price = float(request.form.get('purchase_price', 0) or 0)
            quantity = int(request.form.get('quantity', 1))
            shelf_location = request.form.get('shelf_location', '').strip() or None
            description = request.form.get('description', '').strip() or None

            # Enforce accession number presence. If ADMIN_MANUAL_ACCESSION=1, admin must provide it.
            admin_manual = os.environ.get('ADMIN_MANUAL_ACCESSION', '0')
            if str(admin_manual) in ('1', 'true', 'True'):
                if not accession:
                    flash('Accession number is required by admin policy.', 'danger')
                    return render_template('add_book.html')
            else:
                if not accession:
                    # auto-generate unique accession
                    accession = f'ACC-{int(datetime.utcnow().timestamp())}-{uuid4().hex[:6]}'

            book = Book(
                accession_number=accession,
                isbn=isbn,
                title=title,
                author=author,
                publisher=publisher,
                category=category,
                publication_year=publication_year,
                purchase_price=purchase_price,
                quantity=quantity,
                available_copies=quantity,
                shelf_location=shelf_location,
                description=description
            )
            db.session.add(book)
            db.session.commit()
            log_activity(session['user_id'], 'CREATE', 'Book', book.id, f'Book added: {book.title}')
            flash(f'Book "{book.title}" added successfully!', 'success')
            return redirect(url_for('books_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding book: {str(e)}', 'danger')
    return render_template('add_book.html')


@app.route('/books/<int:book_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    if request.method == 'POST':
        try:
            book.accession_number = request.form.get('accession_number', '').strip() or None
            book.title = request.form.get('title').strip()
            book.author = request.form.get('author').strip()
            book.isbn = request.form.get('isbn', '').strip() or None
            book.publisher = request.form.get('publisher', '').strip() or None
            book.category = request.form.get('category', '').strip() or None
            book.publication_year = int(request.form.get('publication_year', 0)) or None
            book.quantity = int(request.form.get('quantity', 1))
            book.available_copies = max(0, book.available_copies)
            book.purchase_price = float(request.form.get('purchase_price', 0) or 0)
            book.shelf_location = request.form.get('shelf_location', '').strip() or None
            book.description = request.form.get('description', '').strip() or None
            db.session.commit()
            log_activity(session['user_id'], 'UPDATE', 'Book', book.id, f'Book updated: {book.title}')
            flash('Book updated successfully!', 'success')
            return redirect(url_for('books_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating book: {str(e)}', 'danger')
    return render_template('edit_book.html', book=book)


@app.route('/books/<int:book_id>/delete', methods=['POST'])
@admin_required
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    title = book.title
    try:
        db.session.delete(book)
        db.session.commit()
        log_activity(session['user_id'], 'DELETE', 'Book', book_id, f'Book deleted: {title}')
        flash(f'Book "{title}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting book: {str(e)}', 'danger')
    return redirect(url_for('books_list'))


@app.route('/students')
@login_required
def students_list():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    class_filter = request.args.get('class', '').strip()

    query = Student.query
    if search:
        query = query.filter(db.or_(
            Student.full_name.ilike(f'%{search}%'),
            Student.student_id.ilike(f'%{search}%'),
            Student.email.ilike(f'%{search}%')
        ))
    if class_filter:
        query = query.filter_by(class_name=class_filter)

    students = query.paginate(page=page, per_page=20)
    classes = db.session.query(Student.class_name).distinct().all()
    return render_template('students.html', students=students, classes=classes,
                           search=search, class_filter=class_filter)


@app.route('/students/add', methods=['GET', 'POST'])
@login_required
def add_student():
    if request.method == 'POST':
        try:
            sid = request.form.get('student_id').strip()
            if Student.query.filter_by(student_id=sid).first():
                flash('Student ID already exists!', 'danger')
                return render_template('add_student.html')
            student = Student(
                student_id=sid,
                full_name=request.form.get('full_name').strip(),
                enrollment_year=datetime.now().year,
                email=request.form.get('email', '').strip(),
                phone=request.form.get('phone', '').strip(),
                class_name=request.form.get('class_name', '').strip(),
                section=request.form.get('section', '').strip(),
                address=request.form.get('address', '').strip()
            )
            db.session.add(student)
            db.session.commit()
            log_activity(session['user_id'], 'CREATE', 'Student', student.id,
                         f'Student added: {student.full_name} (ID: {sid})')
            flash(f'Student "{student.full_name}" added!', 'success')
            return redirect(url_for('students_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding student: {str(e)}', 'danger')
    return render_template('add_student.html')


@app.route('/students/<int:student_id>')
@login_required
def student_profile(student_id):
    student = Student.query.get_or_404(student_id)
    active_issues = IssuedRecord.query.filter_by(student_id=student_id, is_returned=False).all()
    history = BorrowHistory.query.filter_by(student_id=student_id).order_by(BorrowHistory.issue_date.desc()).all()
    fines = StudentFineReport.query.filter_by(student_id=student_id).order_by(StudentFineReport.issued_date.desc()).all()
    notes = StudentNote.query.filter_by(student_id=student_id).order_by(StudentNote.created_at.desc()).all()
    wishlist = StudentWishlist.query.filter_by(student_id=student_id).order_by(StudentWishlist.added_at.desc()).all()
    all_books = Book.query.order_by(Book.title).all()
    wishlist_book_ids = {w.book_id for w in wishlist}
    return render_template('student_profile.html', student=student,
                           active_issues=active_issues, history=history,
                           fines=fines, notes=notes, wishlist=wishlist,
                           all_books=all_books, wishlist_book_ids=wishlist_book_ids,
                           now=datetime.now())


@app.route('/students/<int:student_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_student(student_id):
    student = Student.query.get_or_404(student_id)
    if request.method == 'POST':
        try:
            student.full_name = request.form.get('full_name').strip()
            student.email = request.form.get('email', '').strip()
            student.phone = request.form.get('phone', '').strip()
            student.class_name = request.form.get('class_name', '').strip()
            student.section = request.form.get('section', '').strip()
            student.address = request.form.get('address', '').strip()
            db.session.commit()
            log_activity(session['user_id'], 'UPDATE', 'Student', student.id, f'Student updated: {student.full_name}')
            flash('Student updated successfully!', 'success')
            return redirect(url_for('student_profile', student_id=student_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating student: {str(e)}', 'danger')
    return render_template('edit_student.html', student=student)


@app.route('/students/<int:student_id>/delete', methods=['POST'])
@admin_required
def delete_student(student_id):
    student = Student.query.get_or_404(student_id)
    name = student.full_name
    try:
        db.session.delete(student)
        db.session.commit()
        log_activity(session['user_id'], 'DELETE', 'Student', student_id, f'Student deleted: {name}')
        flash(f'Student "{name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting student: {str(e)}', 'danger')
    return redirect(url_for('students_list'))


@app.route('/issue-return')
@login_required
def issue_return():
    students = Student.query.filter_by(is_active=True).all()
    books = Book.query.filter(Book.available_copies > 0).all()
    issued = IssuedRecord.query.filter_by(is_returned=False).all()
    students_data = [{'id': s.id, 'student_id': s.student_id, 'name': s.full_name} for s in students]
    books_data = [{'id': b.id, 'title': b.title, 'available_copies': b.available_copies,
                   'low_stock': b.is_low_stock} for b in books]
    issued_data = [{'id': i.id, 'student': {'name': i.student.full_name},
                    'book': {'title': i.book.title}} for i in issued]
    return render_template('issue_return.html', students=students_data,
                           books=books_data, issued=issued_data)


@app.route('/api/issue-book', methods=['POST'])
@limiter.limit('60 per minute')
@login_required
def api_issue_book():
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        book_id = data.get('book_id')
        days = int(data.get('days', 10))
        student = Student.query.get(student_id)
        book = Book.query.get(book_id)
        if not student or not book:
            return jsonify({'error': 'Student or book not found'}), 404
        if book.available_copies <= 0:
            return jsonify({'error': 'No copies available'}), 400
        existing = IssuedRecord.query.filter_by(student_id=student_id, book_id=book_id, is_returned=False).first()
        if existing:
            return jsonify({'error': 'This student already has this book'}), 400
        issue_date = datetime.now()
        due_date = issue_date + timedelta(days=days)
        issued = IssuedRecord(student_id=student_id, book_id=book_id,
                              issue_date=issue_date, due_date=due_date)
        book.available_copies -= 1
        student.books_borrowed += 1
        db.session.add(issued)
        db.session.commit()
        log_activity(session['user_id'], 'ISSUE', 'IssuedRecord', issued.id,
                     f'Book issued: {book.title} to {student.full_name}')
        low_stock_warning = book.is_low_stock
        return jsonify({'success': True, 'message': 'Book issued successfully!',
                        'low_stock_warning': low_stock_warning,
                        'available_copies': book.available_copies}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/return-book', methods=['POST'])
@login_required
def api_return_book():
    try:
        data = request.get_json()
        issued_id = data.get('issued_id')
        condition = data.get('condition', 'good')
        issued = IssuedRecord.query.get(issued_id)
        if not issued or issued.is_returned:
            return jsonify({'error': 'Invalid or already returned'}), 404
        book = issued.book
        student = issued.student
        issued.is_returned = True
        issued.returned_date = datetime.now()
        book.available_copies += 1
        student.books_returned += 1
        history = BorrowHistory(student_id=student.id, book_id=book.id,
                                issue_date=issued.issue_date, due_date=issued.due_date,
                                returned_date=issued.returned_date)
        fine_msg = ''
        if issued.returned_date > issued.due_date:
            days_late = (issued.returned_date - issued.due_date).days
            fine_amount = days_late * 5
            history.status = 'LATE'
            history.fine_paid = fine_amount
            student.fine_balance += fine_amount
            student.books_overdue = max(0, student.books_overdue - 1)
            fine_report = StudentFineReport(student_id=student.id, amount=fine_amount,
                                            description=f'Late return fine for {book.title}')
            db.session.add(fine_report)
            fine_msg = f' Fine of PKR {fine_amount} applied.'
        else:
            history.status = 'ON_TIME'

        damage_msg = ''
        if condition and condition != 'good':
            price = book.purchase_price or 0
            if condition == 'minor':
                damage_fee = round(price * 0.2)
                desc = f'Minor damage fine for {book.title}'
            elif condition == 'major':
                damage_fee = round(price * 0.5)
                desc = f'Major damage fine for {book.title}'
            elif condition == 'lost':
                damage_fee = round(price)
                desc = f'Replacement fine for lost book {book.title}'
                book.status = 'LOST'
            else:
                damage_fee = 0
                desc = f'Damage fine for {book.title}'
            if damage_fee > 0:
                history.fine_paid = (history.fine_paid or 0) + damage_fee
                student.fine_balance += damage_fee
                fine_report = StudentFineReport(student_id=student.id, amount=damage_fee, description=desc)
                db.session.add(fine_report)
                damage_msg = f' Damage fine of PKR {damage_fee} applied.'

        db.session.add(history)
        db.session.commit()
        log_activity(session['user_id'], 'RETURN', 'IssuedRecord', issued.id,
                     f'Book returned: {book.title} from {student.full_name}. Condition: {condition}')
        return jsonify({'success': True, 'message': f'Book returned successfully!{fine_msg}{damage_msg}'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500



@app.route('/issued')
@login_required
def issued_books():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'active').strip()
    query = IssuedRecord.query
    if status == 'active':
        query = query.filter_by(is_returned=False)
    elif status == 'overdue':
        query = query.filter(IssuedRecord.is_returned == False,
                             IssuedRecord.due_date < datetime.now())
    elif status == 'returned':
        query = query.filter_by(is_returned=True)
    issued = query.order_by(IssuedRecord.issue_date.desc()).paginate(page=page, per_page=20)
    return render_template('issued.html', issued=issued, status=status, now=datetime.now())


@app.route('/reports')
@login_required
def reports():
    total_books = Book.query.count()
    total_students = Student.query.count()
    total_issued = IssuedRecord.query.filter_by(is_returned=False).count()
    total_returned = BorrowHistory.query.filter(BorrowHistory.returned_date != None).count()
    top_borrowers = db.session.query(Student, db.func.count(BorrowHistory.id))\
        .join(BorrowHistory).group_by(Student.id)\
        .order_by(db.func.count(BorrowHistory.id).desc()).limit(10).all()
    top_books = db.session.query(Book, db.func.count(BorrowHistory.id))\
        .join(BorrowHistory).group_by(Book.id)\
        .order_by(db.func.count(BorrowHistory.id).desc()).limit(10).all()
    pending_fines = StudentFineReport.query.filter_by(payment_status='PENDING').all()
    total_pending = sum(f.amount for f in pending_fines)
    overdue_books = IssuedRecord.query.filter(
        IssuedRecord.is_returned == False,
        IssuedRecord.due_date < datetime.now()
    ).all()
    low_stock_books = Book.query.filter(
        Book.available_copies <= LOW_STOCK_THRESHOLD,
        Book.status == 'AVAILABLE'
    ).order_by(Book.available_copies.asc()).all()
    return render_template('reports.html',
        total_books=total_books, total_students=total_students,
        total_issued=total_issued, total_returned=total_returned,
        top_borrowers=top_borrowers, top_books=top_books,
        pending_fines=pending_fines, total_pending=total_pending,
        overdue_books=overdue_books, low_stock_books=low_stock_books,
        LOW_STOCK_THRESHOLD=LOW_STOCK_THRESHOLD, now=datetime.now())


@app.route('/leaderboard')
@login_required
def leaderboard():
    borrowers = db.session.query(Student, db.func.count(BorrowHistory.id).label('borrow_count'))\
        .outerjoin(BorrowHistory).group_by(Student.id)\
        .order_by(db.func.count(BorrowHistory.id).desc()).all()
    return render_template('leaderboard.html', borrowers=borrowers, enumerate=enumerate)


@app.route('/settings')
@login_required
def settings():
    user = User.query.get(session['user_id'])
    return render_template('settings.html', user=user)


@app.route('/settings/update-password', methods=['POST'])
@login_required
def update_password():
    user = User.query.get(session['user_id'])
    old_password = request.form.get('old_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    if not user.check_password(old_password):
        flash('Old password is incorrect.', 'danger')
    elif new_password != confirm_password:
        flash('New passwords do not match.', 'danger')
    elif len(new_password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
    else:
        user.set_password(new_password)
        db.session.commit()
        flash('Password updated successfully!', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/update-recovery', methods=['POST'])
@login_required
def update_recovery():
    user = User.query.get(session['user_id'])
    recovery_answer = request.form.get('recovery_answer', '').strip()
    if recovery_answer:
        user.recovery_answer = bcrypt.generate_password_hash(recovery_answer).decode('utf-8')
        db.session.commit()
        flash('Recovery answer updated!', 'success')
    else:
        flash('Please enter a recovery answer.', 'danger')
    return redirect(url_for('settings'))


@app.route('/admin/users')
@admin_required
def manage_users():
    users = User.query.all()
    return render_template('manage_users.html', users=users)


@app.route('/admin/users/add', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        try:
            if User.query.filter_by(username=request.form.get('username')).first():
                flash('Username already exists!', 'danger')
                return render_template('add_user.html')
            user = User(
                username=request.form.get('username').strip(),
                full_name=request.form.get('full_name', '').strip(),
                role=request.form.get('role', 'LIBRARIAN')
            )
            user.set_password(request.form.get('password'))
            db.session.add(user)
            db.session.commit()
            log_activity(session['user_id'], 'CREATE', 'User', user.id, f'User created: {user.username}')
            flash(f'User "{user.username}" created successfully!', 'success')
            return redirect(url_for('manage_users'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating user: {str(e)}', 'danger')
    return render_template('add_user.html')


@app.route('/admin/backups')
@admin_required
def list_backups():
    backups = Backup.query.order_by(Backup.created_at.desc()).all()
    return render_template('manage_backups.html', backups=backups)


@app.route('/admin/backups/create', methods=['POST'])
@admin_required
def create_backup():
    # Delegate to helper that performs the backup and returns a result dict
    result = perform_backup()
    if result.get('success'):
        flash('Backup created successfully.', 'success')
    else:
        flash(f"Backup failed: {result.get('message')}", 'danger')
    return redirect(url_for('list_backups'))


@app.route('/admin/backups/download/<int:backup_id>')
@admin_required
def download_backup(backup_id):
    bk = Backup.query.get_or_404(backup_id)
    backup_dir = os.path.join(app.instance_path, 'backups')
    return send_from_directory(backup_dir, bk.filename, as_attachment=True)


@app.route('/students/<int:student_id>/notes/add', methods=['POST'])
@login_required
def add_student_note(student_id):
    student = Student.query.get_or_404(student_id)
    content_text = request.form.get('content', '').strip()
    if not content_text:
        flash('Note cannot be empty.', 'danger')
        return redirect(url_for('student_profile', student_id=student_id))
    try:
        note = StudentNote(student_id=student_id, user_id=session['user_id'], content=content_text)
        db.session.add(note)
        db.session.commit()
        log_activity(session['user_id'], 'CREATE', 'StudentNote', note.id,
                     f'Note added for student: {student.full_name}')
        flash('Note added successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding note: {str(e)}', 'danger')
    return redirect(url_for('student_profile', student_id=student_id))


@app.route('/students/<int:student_id>/notes/<int:note_id>/delete', methods=['POST'])
@login_required
def delete_student_note(student_id, note_id):
    note = StudentNote.query.get_or_404(note_id)
    user = User.query.get(session['user_id'])
    if note.user_id != session['user_id'] and user.role != 'ADMIN':
        flash('You can only delete your own notes.', 'danger')
        return redirect(url_for('student_profile', student_id=student_id))
    try:
        db.session.delete(note)
        db.session.commit()
        flash('Note deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting note: {str(e)}', 'danger')
    return redirect(url_for('student_profile', student_id=student_id))


@app.route('/students/<int:student_id>/wishlist/add', methods=['POST'])
@admin_required
def add_wishlist_item(student_id):
    student = Student.query.get_or_404(student_id)
    book_id = request.form.get('book_id', type=int)
    wish_note = request.form.get('wish_note', '').strip()
    if not book_id:
        flash('Please select a book.', 'danger')
        return redirect(url_for('student_profile', student_id=student_id))
    book = Book.query.get_or_404(book_id)
    existing = StudentWishlist.query.filter_by(student_id=student_id, book_id=book_id).first()
    if existing:
        flash('This book is already on the wishlist.', 'warning')
        return redirect(url_for('student_profile', student_id=student_id))
    try:
        item = StudentWishlist(student_id=student_id, book_id=book_id,
                               added_by=session['user_id'], note=wish_note or None)
        db.session.add(item)
        db.session.commit()
        log_activity(session['user_id'], 'CREATE', 'StudentWishlist', item.id,
                     f'Wishlist: {book.title} added for {student.full_name}')
        flash(f'"{book.title}" added to wishlist!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding to wishlist: {str(e)}', 'danger')
    return redirect(url_for('student_profile', student_id=student_id))


def perform_backup():
    """Create a backup and optionally upload to S3. Returns dict with success,message, path, stored_name."""
    try:
        backup_dir = os.path.join(app.instance_path, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f'backup-{timestamp}.zip'
        filepath = os.path.join(backup_dir, filename)

        final_path = None
        # If using sqlite, copy the file and zip it
        if db_uri.startswith('sqlite:'):
            sqlite_path = db_uri.replace('sqlite:///', '')
            temp_dir = os.path.join(backup_dir, f'tmp-{timestamp}')
            os.makedirs(temp_dir, exist_ok=True)
            shutil.copy2(sqlite_path, os.path.join(temp_dir, os.path.basename(sqlite_path)))
            shutil.make_archive(filepath.replace('.zip', ''), 'zip', temp_dir)
            final_path = filepath
            enc_key = os.environ.get('BACKUP_ENCRYPTION_KEY')
            if enc_key:
                try:
                    fernet = Fernet(enc_key)
                    with open(filepath, 'rb') as f:
                        data_bytes = f.read()
                    encrypted = fernet.encrypt(data_bytes)
                    enc_file = filepath + '.enc'
                    with open(enc_file, 'wb') as ef:
                        ef.write(encrypted)
                    os.remove(filepath)
                    final_path = enc_file
                    filename = os.path.basename(final_path)
                except Exception:
                    pass
            # compute size
            size = os.path.getsize(final_path)
            storage = 'local'
            stored_name = os.path.basename(final_path)
            bk = Backup(filename=stored_name, storage=storage, size=size)
            db.session.add(bk)
            db.session.commit()
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
            # Also copy a persistent copy outside application instance so it survives reinstall
            try:
                persistent_dir = os.environ.get('PERSISTENT_BACKUP_DIR') or os.path.join(os.path.expanduser('~'), '.librarysystempro_backups')
                os.makedirs(persistent_dir, exist_ok=True)
                persistent_path = os.path.join(persistent_dir, os.path.basename(final_path))
                shutil.copy2(final_path, persistent_path)
            except Exception:
                pass
            return {'success': True, 'path': final_path, 'stored_name': stored_name}

        # For Postgres try pg_dump if available
        elif db_uri.startswith('postgres') or db_uri.startswith('postgresql'):
            dump_path = os.path.join(backup_dir, f'db-{timestamp}.sql')
            pg_dump = os.environ.get('PG_DUMP_PATH', 'pg_dump')
            cmd = [pg_dump, db_uri, '-f', dump_path]
            subprocess.run(cmd, check=True)
            shutil.make_archive(filepath.replace('.zip', ''), 'zip', backup_dir)
            final_path = filepath
            enc_key = os.environ.get('BACKUP_ENCRYPTION_KEY')
            if enc_key:
                try:
                    fernet = Fernet(enc_key)
                    with open(filepath, 'rb') as f:
                        data_bytes = f.read()
                    encrypted = fernet.encrypt(data_bytes)
                    enc_file = filepath + '.enc'
                    with open(enc_file, 'wb') as ef:
                        ef.write(encrypted)
                    os.remove(filepath)
                    final_path = enc_file
                    filename = os.path.basename(final_path)
                except Exception:
                    pass

            size = os.path.getsize(final_path)
            storage = 'local'
            stored_name = os.path.basename(final_path)
            bk = Backup(filename=stored_name, storage=storage, size=size)
            db.session.add(bk)
            db.session.commit()
            # Copy persistent backup for reinstall durability
            try:
                persistent_dir = os.environ.get('PERSISTENT_BACKUP_DIR') or os.path.join(os.path.expanduser('~'), '.librarysystempro_backups')
                os.makedirs(persistent_dir, exist_ok=True)
                persistent_path = os.path.join(persistent_dir, os.path.basename(final_path))
                shutil.copy2(final_path, persistent_path)
            except Exception:
                pass
            return {'success': True, 'path': final_path, 'stored_name': stored_name}

        else:
            return {'success': False, 'message': 'Unsupported database for automatic backup.'}
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return {'success': False, 'message': str(e)}


def prune_old_backups(retention_days=None):
    try:
        if retention_days is None:
            retention_days = int(os.environ.get('BACKUP_RETENTION_DAYS', 30))
        cutoff = datetime.now() - timedelta(days=retention_days)
        # Delete backups older than cutoff from DB and local stores
        old = Backup.query.filter(Backup.created_at < cutoff).all()
        for b in old:
            try:
                # remove from instance backups
                try:
                    local_path = os.path.join(app.instance_path, 'backups', os.path.basename(b.filename))
                    if os.path.exists(local_path):
                        os.remove(local_path)
                except Exception:
                    pass
                # remove from persistent dir
                try:
                    persistent_dir = os.environ.get('PERSISTENT_BACKUP_DIR') or os.path.join(os.path.expanduser('~'), '.librarysystempro_backups')
                    persistent_path = os.path.join(persistent_dir, os.path.basename(b.filename))
                    if os.path.exists(persistent_path):
                        os.remove(persistent_path)
                except Exception:
                    pass
                db.session.delete(b)
                db.session.commit()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass

        # Enforce max files per store
        try:
            max_files = int(os.environ.get('BACKUP_MAX_FILES_PER_STORE', 100000))
        except Exception:
            max_files = 100000

        # prune instance backups by count
        try:
            inst_dir = os.path.join(app.instance_path, 'backups')
            files = [os.path.join(inst_dir, f) for f in os.listdir(inst_dir)] if os.path.isdir(inst_dir) else []
            files = [f for f in files if os.path.isfile(f)]
            files.sort(key=lambda p: os.path.getmtime(p))
            while len(files) > max_files:
                oldest = files.pop(0)
                try:
                    os.remove(oldest)
                except Exception:
                    pass

        except Exception:
            pass

        # prune persistent backups by count
        try:
            persistent_dir = os.environ.get('PERSISTENT_BACKUP_DIR') or os.path.join(os.path.expanduser('~'), '.librarysystempro_backups')
            files = [os.path.join(persistent_dir, f) for f in os.listdir(persistent_dir)] if os.path.isdir(persistent_dir) else []
            files = [f for f in files if os.path.isfile(f)]
            files.sort(key=lambda p: os.path.getmtime(p))
            while len(files) > max_files:
                oldest = files.pop(0)
                try:
                    os.remove(oldest)
                except Exception:
                    pass
        except Exception:
            pass

        return True
    except Exception:
        return False


@app.route('/students/<int:student_id>/wishlist/<int:item_id>/delete', methods=['POST'])
@admin_required
def delete_wishlist_item(student_id, item_id):
    item = StudentWishlist.query.get_or_404(item_id)
    try:
        db.session.delete(item)
        db.session.commit()
        flash('Wishlist item removed.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error removing wishlist item: {str(e)}', 'danger')
    return redirect(url_for('student_profile', student_id=student_id))


def log_activity(user_id, action, entity_type, entity_id, description):
    try:
        ip = None
        ua = None
        try:
            ip = request.remote_addr
            ua = request.headers.get('User-Agent')
        except Exception:
            pass
        log = ActivityLog(user_id=user_id, action=action, entity_type=entity_type,
                          entity_id=entity_id, description=description,
                          ip_address=ip, user_agent=ua)
        db.session.add(log)
        db.session.commit()
    except:
        pass


def init_default_admin():
    if User.query.count() == 0:
        admin = User(username='admin', full_name='Administrator', role='ADMIN')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()


def create_app():
    with app.app_context():
        db.create_all()
        # If using Postgres, create helpful extensions and indexes for search
        try:
            if db.engine.dialect.name == 'postgresql':
                # Enable pg_trgm for fuzzy search
                db.session.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
                db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_books_title_trgm ON books USING gin (lower(title) gin_trgm_ops)"))
                db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_books_author_trgm ON books USING gin (lower(author) gin_trgm_ops)"))
                db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_books_isbn_trgm ON books USING gin (lower(isbn) gin_trgm_ops)"))
                db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_students_fullname_trgm ON students USING gin (lower(full_name) gin_trgm_ops)"))
                db.session.commit()
        except Exception:
            db.session.rollback()
        init_default_admin()
        # warm Redis cache if available
        try:
            if cache_redis:
                cache_redis.ping()
        except Exception:
            pass

        # Scheduled backups via APScheduler
        try:
            enable_sched = os.environ.get('ENABLE_SCHEDULED_BACKUPS', '1')
            if str(enable_sched) not in ('0', 'false', 'False'):
                backup_hour = int(os.environ.get('BACKUP_HOUR', 2))
                backup_min = int(os.environ.get('BACKUP_MIN', 0))
                retention_days = int(os.environ.get('BACKUP_RETENTION_DAYS', 30))
                scheduler = BackgroundScheduler()
                # daily backup
                scheduler.add_job(func=lambda: perform_backup(), trigger='cron', hour=backup_hour, minute=backup_min, id='daily_backup', replace_existing=True)
                # daily pruning
                scheduler.add_job(func=lambda: prune_old_backups(retention_days), trigger='cron', hour=backup_hour+1 if backup_hour < 23 else 0, minute=backup_min, id='prune_backups', replace_existing=True)
                scheduler.start()
                atexit.register(lambda: scheduler.shutdown())
        except Exception:
            pass


    @app.after_request
    def set_security_headers(response):
        # Content Security Policy (minimal, adjust for your needs)
        csp = "default-src 'self'; script-src 'self' https: 'unsafe-inline' 'unsafe-eval'; style-src 'self' https: 'unsafe-inline'; img-src 'self' data: https:;"
        response.headers['Content-Security-Policy'] = csp
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=()'
        # HSTS for HTTPS enforcement in production
        if app.config.get('SESSION_COOKIE_SECURE'):
            response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
        return response
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=False, host='0.0.0.0', port=5000)
