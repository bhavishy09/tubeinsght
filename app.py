import os
from dotenv import load_dotenv
import random
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, request
from database import (
    init_db, create_user, verify_user, get_user_by_id,
    add_prediction, get_user_predictions, get_sentiment_stats,
    add_tracker_history, get_tracker_history
)
from services import gemini_chat
from services.youtube import analyze_youtube_comments, extract_video_id
from services.views import views
from services.youtube_tracker import track_video_stats

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', 'dev-secret-key-change-in-production')
app.register_blueprint(views, url_prefix='/')

try:
    init_db()
except Exception as e:
    print(f"Warning: Database initialization failed (expected if DATABASE_URL is missing on Vercel): {e}")



@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Please fill in all fields', 'error')
            return render_template('login.html')
        
        user = verify_user(email, password)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash(f'Welcome back, {user["username"]}!', 'success')
            return redirect(url_for('predict'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if not username or not email or not password:
            flash('Please fill in all fields', 'error')
            return render_template('signup.html')
        
        if '@' not in email or '.' not in email:
            flash('Please enter a valid email address', 'error')
            return render_template('signup.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters long', 'error')
            return render_template('signup.html')
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('signup.html')
        
        user_id = create_user(username, email, password)
        if user_id:
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Username or email already exists', 'error')
    
    return render_template('signup.html')



@app.route('/chatbot')
def chatbot_page():
    video_id = request.args.get('video_id')
    hope_count = request.args.get('hope_count')
    hate_count = request.args.get('hate_count')
    
    initial_message = "Hello! I'm your AI assistant. Ask me anything about content creation, YouTube, or sentiment analysis."

    if video_id and hope_count is not None and hate_count is not None:
        # If context is provided from a redirect, generate a contextual prompt
        prompt = (
            f"The user was just redirected to me after analyzing the YouTube video with ID '{video_id}'. "
            f"The analysis found {hate_count} negative comments and {hope_count} positive comments. "
            f"Since the negative comments were high, greet the user, acknowledge the analysis results, "
            f"and offer specific, actionable advice on how a content creator can manage, understand, or respond to this negative feedback. "
            f"Keep the tone helpful and encouraging. Start by saying something like 'I noticed your video...'."
        )
        try:
            initial_message = gemini_chat.chatbot(prompt)
        except Exception as e:
            print(f"Error getting initial chatbot message: {e}")
            initial_message = "I noticed your recent video analysis showed a high number of negative comments. I'm here to help you with that. How can I assist?"

    return render_template('chatbot.html', initial_message=initial_message)

@app.route('/predict', methods=['GET', 'POST'])
def predict():
    if 'user_id' not in session:
        flash('Please log in to make predictions', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        video_input = request.form.get('video_id', '').strip()
        
        if not video_input:
            flash('Please enter a YouTube video ID or URL', 'error')
            return render_template('predict.html')
        
        video_id = extract_video_id(video_input)
        if not video_id:
            flash('Please enter a valid YouTube video ID or URL', 'error')
            return render_template('predict.html')

        try:
            analysis_results = analyze_youtube_comments(video_id)
        except ConnectionError as e:
            flash(str(e), 'error')
            return redirect(url_for('predict'))

        if analysis_results.get("error"):
            flash(analysis_results["error"], 'error')
            return render_template('predict.html')

        hope_count = analysis_results.get("hope_count", 0)
        hate_count = analysis_results.get("hate_count", 0)

        show_chatbot_suggestion = hate_count > hope_count
        if show_chatbot_suggestion:
            flash('High level of negative comments detected. Our AI assistant can help you understand and manage this.', 'warning')

        if hope_count > hate_count:
            sentiment = 'Positive' # Map Hope to Positive
        elif hate_count > hope_count:
            sentiment = 'Negative' # Map Hate to Negative
        else:
            sentiment = 'Neutral'

        add_prediction(session['user_id'], video_id, sentiment)
        
        flash(f'Prediction completed! Overall Sentiment: {sentiment}', 'success')
        
        recent_predictions = get_user_predictions(session['user_id'], limit=5)
        return render_template('predict.html', 
                                latest_prediction={
                                    'video_id': video_id, 
                                    'sentiment': sentiment,
                                    'hope_count': hope_count,
                                    'hate_count': hate_count,
                                    'comments_processed': analysis_results.get("comments_processed", 0),
                                    'hope_comments': analysis_results.get("hope_comments", []),
                                    'hate_comments': analysis_results.get("hate_comments", [])
                                },
                                recent_predictions=recent_predictions,
                                show_chatbot_suggestion=show_chatbot_suggestion)
    
    recent_predictions = get_user_predictions(session['user_id'], limit=5)
    return render_template('predict.html', recent_predictions=recent_predictions)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Please log in to view your dashboard', 'error')
        return redirect(url_for('login'))
    
    predictions = get_user_predictions(session['user_id'])
    stats = get_sentiment_stats(session['user_id'])
    tracker_history = get_tracker_history(session['user_id'], limit=3)
    
    sentiment_data = {
        'Positive': stats.get('Positive', 0),
        'Neutral': stats.get('Neutral', 0),
        'Negative': stats.get('Negative', 0)
    }
    
    return render_template('dashboard.html', 
                         predictions=predictions, 
                         sentiment_data=sentiment_data,
                         tracker_history=tracker_history)

@app.route('/youtube_tracker', methods=['GET', 'POST'])
def youtube_tracker():
    if 'user_id' not in session:
        flash('Please log in to use the tracker', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        video_id = request.form.get('video_id')
        try:
            interval = int(request.form.get('interval', 5))
            samples = int(request.form.get('samples', 5))
        except (ValueError, TypeError):
            flash('Interval and samples must be integers.', 'error')
            return render_template('youtube_tracker.html')

        if not video_id:
            flash('Please provide a YouTube Video ID.', 'error')
            return render_template('youtube_tracker.html')

        flash('Starting to track video stats. This might take a while...', 'info')
        
        try: 
            # Note: This is the fallback blocking method. 
            # For Vercel, the frontend JS handles polling via /api/track instead.
            from services.youtube_tracker import track_video_stats
            plots = track_video_stats(video_id, interval, samples)
            if not plots:
                flash('Could not generate any plots. The video might not exist or the API key may be invalid.', 'error')
                return render_template('youtube_tracker.html', video_id=video_id, interval=interval, samples=samples)

            if 'user_id' in session:
                add_tracker_history(session['user_id'], video_id, plots)

            flash('Tracking complete!', 'success')
            return render_template('youtube_tracker.html', plots=plots, video_id=video_id, interval=interval, samples=samples)

        except Exception as e:
            flash(f'An error occurred: {e}', 'error')
            return render_template('youtube_tracker.html', video_id=video_id, interval=interval, samples=samples)

    return render_template('youtube_tracker.html')

@app.route('/api/track', methods=['GET'])
def api_track():
    """API endpoint for frontend polling of YouTube stats without blocking."""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    video_id = request.args.get('video_id')
    if not video_id:
        return jsonify({'error': 'Missing video_id'}), 400
        
    from services.youtube_tracker import get_single_sample
    try:
        sample = get_single_sample(video_id)
        return jsonify(sample)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/track/save', methods=['POST'])
def api_track_save():
    """API endpoint to generate plots from polled data and save to history."""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    data = request.json
    video_id = data.get('video_id')
    data_list = data.get('data_list', [])
    interval = data.get('interval', 1)
    
    if not video_id or not data_list:
        return jsonify({'error': 'Missing data'}), 400
        
    from services.youtube_tracker import generate_plots_from_data
    try:
        plots = generate_plots_from_data(video_id, data_list, interval)
        if plots:
            add_tracker_history(session['user_id'], video_id, plots)
            return jsonify({'success': True, 'plots': plots})
        else:
            return jsonify({'error': 'Failed to generate plots'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('views.home'))


# chat enpoint
@app.route("/chat/<prompt>", methods=["POST"])
def chating(prompt):
    try:
        response_data = gemini_chat.chatbot(prompt)
        return jsonify({
            "status": "ok",
            "message": response_data
        })
    
    except Exception as err:
        return jsonify({
            "status": "error",
            "message": f"An error occurred: {str(err)}"
        })



import os

if __name__ == "__main__":
    # Use the port assigned by Render, or default to 10000 locally
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)