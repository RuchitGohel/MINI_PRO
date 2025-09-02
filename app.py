import os
import sqlite3
import uuid
from datetime import timedelta

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'app.db')
CHARTS_DIR = os.path.join(BASE_DIR, 'static', 'charts')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

os.makedirs(CHARTS_DIR, exist_ok=True)


def create_app() -> Flask:
	app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
	app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-me')
	app.permanent_session_lifetime = timedelta(hours=6)

	initialize_database()

	@app.context_processor
	def inject_globals():
		return {
			"app_title": "CSV Data Visualizer",
			"current_user": session.get('username')
		}

	@app.route('/')
	def index():
		if session.get('user_id'):
			return redirect(url_for('visualize'))
		return redirect(url_for('login'))

	@app.route('/signup', methods=['GET', 'POST'])
	def signup():
		if request.method == 'POST':
			username = request.form.get('username', '').strip()
			password = request.form.get('password', '').strip()
			if not username or not password:
				flash('Username and password are required.', 'error')
				return render_template('signup.html')
			if user_exists(username):
				flash('Username already exists. Please choose another.', 'error')
				return render_template('signup.html')
			create_user(username, password)
			flash('Account created. Please log in.', 'success')
			return redirect(url_for('login'))
		return render_template('signup.html')

	@app.route('/login', methods=['GET', 'POST'])
	def login():
		if request.method == 'POST':
			username = request.form.get('username', '').strip()
			password = request.form.get('password', '').strip()
			user = authenticate_user(username, password)
			if user:
				session.permanent = True
				session['user_id'] = user['id']
				session['username'] = user['username']
				return redirect(url_for('visualize'))
			flash('Invalid credentials.', 'error')
		return render_template('login.html')

	@app.route('/logout')
	def logout():
		session.clear()
		flash('Logged out successfully.', 'success')
		return redirect(url_for('login'))

	@app.route('/visualize', methods=['GET', 'POST'])
	def visualize():
		if not session.get('user_id'):
			return redirect(url_for('login'))

		chart_url = None
		download_url = None
		chart_error_message = None

		if request.method == 'POST':
			file = request.files.get('csv_file')
			chart_type = (request.form.get('chart_type') or '').strip() or None
			x_column_raw = (request.form.get('x_column') or '').strip()
			y_column_raw = (request.form.get('y_column') or '').strip()
			x_column = x_column_raw or None
			y_column = y_column_raw or None

			if not file or file.filename == '':
				chart_error_message = 'Please upload a CSV file.'
			else:
				try:
					dataframe = pd.read_csv(file)
					temporary_filename = f"{uuid.uuid4().hex}.png"
					output_path = os.path.join(CHARTS_DIR, temporary_filename)

					generate_chart_png(
						dataframe=dataframe,
						chart_type=chart_type,
						output_path=output_path,
						x_column=x_column,
						y_column=y_column,
					)

					chart_url = url_for('static', filename=f"charts/{temporary_filename}")
					download_url = url_for('download_chart', filename=temporary_filename)
				except Exception as exc:
					chart_error_message = f"Error generating chart: {exc}"

		columns_preview = []
		return render_template('visualize.html', chart_url=chart_url, download_url=download_url, chart_error_message=chart_error_message, columns_preview=columns_preview)

	@app.route('/download/<filename>')
	def download_chart(filename: str):
		if not session.get('user_id'):
			return redirect(url_for('login'))
		file_path = os.path.join(CHARTS_DIR, filename)
		if not os.path.isfile(file_path):
			abort(404)
		return send_file(file_path, as_attachment=True, download_name='chart.png', mimetype='image/png')

	@app.route('/team')
	def team():
		return render_template('team.html')

	return app


def initialize_database() -> None:
	connection = sqlite3.connect(DB_PATH)
	try:
		cursor = connection.cursor()
		cursor.execute(
			"""
			CREATE TABLE IF NOT EXISTS users (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				username TEXT UNIQUE NOT NULL,
				password TEXT NOT NULL
			);
			"""
		)
		connection.commit()
	finally:
		connection.close()


def user_exists(username: str) -> bool:
	connection = sqlite3.connect(DB_PATH)
	try:
		cursor = connection.cursor()
		cursor.execute("SELECT 1 FROM users WHERE username = ?", (username,))
		return cursor.fetchone() is not None
	finally:
		connection.close()


def create_user(username: str, password: str) -> None:
	connection = sqlite3.connect(DB_PATH)
	try:
		cursor = connection.cursor()
		cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
		connection.commit()
	finally:
		connection.close()


def authenticate_user(username: str, password: str):
	connection = sqlite3.connect(DB_PATH)
	connection.row_factory = sqlite3.Row
	try:
		cursor = connection.cursor()
		cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
		row = cursor.fetchone()
		return dict(row) if row else None
	finally:
		connection.close()


def _infer_axes(dataframe: pd.DataFrame, chart_type: str, x_column: str | None, y_column: str | None) -> tuple[str | None, str | None]:
	# Identify numeric and non-numeric columns
	numeric_columns = dataframe.select_dtypes(include=['number']).columns.tolist()
	nonnumeric_columns = [c for c in dataframe.columns if c not in numeric_columns]

	# Try to find a datetime-like column
	date_like = None
	for column_name in dataframe.columns:
		try:
			parsed = pd.to_datetime(dataframe[column_name], errors='coerce', infer_datetime_format=True)
			if parsed.notna().mean() > 0.8:
				date_like = column_name
				break
		except Exception:
			pass

	if chart_type == 'line':
		inferred_x = x_column or date_like or (dataframe.columns[0] if len(dataframe.columns) > 0 else None)
		inferred_y = y_column or (next((c for c in numeric_columns if c != inferred_x), None))
		return inferred_x, inferred_y

	if chart_type == 'scatter':
		if not x_column or not y_column:
			# pick the first two numeric columns
			if len(numeric_columns) >= 2:
				return numeric_columns[0], numeric_columns[1]
			elif len(numeric_columns) == 1:
				return numeric_columns[0], numeric_columns[0]
		return x_column, y_column

	if chart_type == 'bar':
		# Our bar implementation uses value_counts on a single column (y)
		inferred_y = y_column
		if not inferred_y:
			# prefer a categorical with reasonable unique count
			candidate = None
			best_uniques = None
			for c in nonnumeric_columns:
				unique_count = dataframe[c].nunique(dropna=True)
				if unique_count <= 30 and unique_count >= 2:
					candidate = c
					best_uniques = unique_count
					break
			inferred_y = candidate or (nonnumeric_columns[0] if nonnumeric_columns else (numeric_columns[0] if numeric_columns else None))
		return None, inferred_y

	if chart_type == 'pie':
		# Pie uses value_counts on y
		inferred_y = y_column
		if not inferred_y:
			candidate = None
			for c in nonnumeric_columns:
				unique_count = dataframe[c].nunique(dropna=True)
				if unique_count <= 10 and unique_count >= 2:
					candidate = c
					break
			inferred_y = candidate or (nonnumeric_columns[0] if nonnumeric_columns else (numeric_columns[0] if numeric_columns else None))
		return None, inferred_y

	return x_column, y_column


def generate_chart_png(dataframe: pd.DataFrame, chart_type: str, output_path: str, x_column: str | None, y_column: str | None) -> None:
	plt.figure(figsize=(8, 5))
	plt.clf()

	# Auto-detect axes if missing
	x_column, y_column = _infer_axes(dataframe, chart_type, x_column, y_column)

	if chart_type == 'pie':
		if not y_column:
			raise ValueError('Could not infer a column for pie chart')
		series = dataframe[y_column].value_counts().head(10)
		series.plot(kind='pie', autopct='%1.1f%%', startangle=90)
		plt.ylabel('')
		plt.title(f'Pie Chart of {y_column}')

	elif chart_type == 'bar':
		if not y_column:
			raise ValueError('Could not infer a column for bar chart')
		grouped = dataframe[y_column].value_counts().head(20)
		grouped.plot(kind='bar')
		plt.title(f'Bar Chart of {y_column}')
		plt.xlabel(y_column)
		plt.ylabel('Count')

	elif chart_type == 'line':
		if not x_column or not y_column:
			raise ValueError('Could not infer X and Y for line chart')
		try:
			dataframe_sorted = dataframe.sort_values(by=x_column)
		except Exception:
			dataframe_sorted = dataframe
		plt.plot(dataframe_sorted[x_column], dataframe_sorted[y_column])
		plt.title(f'Line Chart: {y_column} vs {x_column}')
		plt.xlabel(x_column)
		plt.ylabel(y_column)

	elif chart_type == 'scatter':
		if not x_column or not y_column:
			raise ValueError('Could not infer X and Y for scatter plot')
		plt.scatter(dataframe[x_column], dataframe[y_column])
		plt.title(f'Scatter Plot: {y_column} vs {x_column}')
		plt.xlabel(x_column)
		plt.ylabel(y_column)

	else:
		raise ValueError('Unsupported chart type')

	plt.tight_layout()
	plt.savefig(output_path, format='png')
	plt.close()


if __name__ == '__main__':
	app = create_app()
	app.run(debug=True)
