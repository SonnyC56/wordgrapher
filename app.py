from flask import Flask, render_template, request, send_file
import matplotlib.pyplot as plt
import io
import base64

app = Flask(__name__)

def create_graph(text):
    # Convert text to lowercase and get ASCII values
    ascii_values = [ord(c) for c in text.lower()]
    
    # Create the plot
    plt.figure(figsize=(10, 6))
    plt.plot(ascii_values, marker='o')
    plt.title('ASCII Value Graph')
    plt.xlabel('Character Position')
    plt.ylabel('ASCII Value')
    plt.grid(True)
    
    # Save plot to bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close()
    buf.seek(0)
    return buf

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/graph', methods=['POST'])
def graph():
    text = request.form['text']
    if not text:
        return 'No text provided', 400
    
    # Generate graph
    img_buf = create_graph(text)
    img_base64 = base64.b64encode(img_buf.getvalue()).decode()
    
    return render_template('result.html', 
                         image_data=img_base64,
                         original_text=text)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
