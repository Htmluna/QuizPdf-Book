from flask import Flask, render_template, request, redirect, url_for, send_from_directory
import os
from werkzeug.utils import secure_filename
import pypdf
import time
import google.generativeai as genai
import re  # Importa a biblioteca re

# Configuração da API do Gemini
GOOGLE_API_KEY = "API KEY "  # Substitua pela sua chave de API
genai.configure(api_key=GOOGLE_API_KEY)

# Seleciona o modelo Gemini Pro para geração de texto
model = genai.GenerativeModel('gemini-2.0-flash')


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'pdf'}
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def parse_page_input(page_input):
    pages = []
    parts = page_input.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                pages.extend(range(start - 1, end))
            except ValueError:
                raise ValueError("Formato de intervalo inválido. Use 'inicio-fim'.")
        else:
            try:
                pages.append(int(part) - 1)
            except ValueError:
                raise ValueError("Número de página inválido.")
    return sorted(list(set(p for p in pages if p >= 0)))


def translate_text(text, target_language="en"):
    """Traduz o texto para o idioma especificado usando a API do Gemini."""
    try:
        prompt = f"Traduza o seguinte texto para {target_language}: {text}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Erro na tradução: {e}")
        return None


def generate_questions_and_alternatives(text, num_questions=3):
    """Gera perguntas e alternativas usando a API do Gemini."""
    try:
        # Traduz o texto para inglês (opcional, mas pode melhorar a qualidade)
        translated_text = translate_text(text, target_language="en")
        if not translated_text:
            return []

        prompt = f"""Gere {num_questions} perguntas de múltipla escolha sobre o seguinte texto:
        {translated_text}

        Para cada pergunta, forneça 4 alternativas, sendo uma correta e 3 incorretas.
        Formate a saída da seguinte forma:

        Pergunta: [pergunta]
        A) [alternativa A]
        B) [alternativa B]
        C) [alternativa C]
        D) [alternativa D]
        Resposta Correta: [letra da alternativa correta]
        """

        response = model.generate_content(prompt)
        gemini_output = response.text

        # Analisa a resposta do Gemini
        questions = parse_gemini_response(gemini_output)
        return questions
    except Exception as e:
        print(f"Erro na geração de perguntas e alternativas: {e}")
        return []


def parse_gemini_response(response_text):
    """Analisa a resposta do Gemini e extrai perguntas e alternativas."""
    questions = []
    # Divide a resposta em blocos de perguntas
    question_blocks = re.split(r"Pergunta:", response_text)[1:]
    for block in question_blocks:
        try:
            lines = block.split("\n")
            question = lines[0].strip()

            alternatives = {}
            for line in lines[1:]:
                line = line.strip()
                if re.match(r"[A-D]\)", line):
                    letter = line[0]
                    text = line[3:].strip()
                    alternatives[letter] = text

            correct_answer_line = next((line for line in lines if "Resposta Correta:" in line), None)
            correct_answer = correct_answer_line.split(":")[1].strip() if correct_answer_line else None

            questions.append({
                "question": question,
                "alternatives": alternatives,
                "correct_answer": correct_answer
            })
        except Exception as e:
            print(f"Erro ao analisar bloco de pergunta: {e}")

    return questions


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'pdf_file' not in request.files:
            return render_template('index.html', error='Nenhum arquivo selecionado.')

        file = request.files['pdf_file']
        if file.filename == '':
            return render_template('index.html', error='Nenhum arquivo selecionado.')

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            return redirect(url_for('extract_text', filename=filename))  # Redireciona após o upload
        else:
            return render_template('index.html', error='Tipo de arquivo não permitido. Apenas PDF.')
    return render_template('index.html')  # Exibe a página de upload


@app.route('/extract/<filename>', methods=['GET', 'POST'])
def extract_text(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    if not os.path.exists(filepath):
        return render_template('index.html', error='Arquivo não encontrado.')

    try:
        with open(filepath, 'rb') as file:
            reader = pypdf.PdfReader(file)
            num_pages = len(reader.pages)

            if request.method == 'POST':
                pages_input = request.form.get('pages')
                if pages_input:
                    try:
                        pages = parse_page_input(pages_input)

                        extracted_text = ""
                        for page_num in pages:
                            if 0 <= page_num < num_pages:
                                page = reader.pages[page_num]
                                extracted_text += page.extract_text() + "\n\n"

                        max_text_length = 1000 # Limita o texto a 500 caracteres
                        extracted_text = extracted_text[:max_text_length]

                        # Gera as perguntas e alternativas
                        questions = generate_questions_and_alternatives(extracted_text)

                        return render_template('extract.html', filename=filename, text=extracted_text,
                                               questions=questions, num_pages=num_pages)

                    except ValueError as e:
                        return render_template('extract.html', filename=filename, error=f'Entrada inválida: {e}. Use números separados por vírgula ou intervalos (ex: 1, 3, 5-10).',
                                               num_pages=num_pages)
                    except Exception as e:
                        print(f"Erro ao processar o arquivo: {e}")
                        return render_template('index.html', error=f'Erro ao processar o arquivo: {e}')

            return render_template('extract.html', filename=filename, num_pages=num_pages)

    except Exception as e:
        print(f"Erro ao processar o arquivo: {e}")
        return render_template('index.html', error=f'Erro ao processar o arquivo: {e}')


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    app.run(debug=True)
