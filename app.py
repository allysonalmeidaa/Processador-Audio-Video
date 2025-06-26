import os
from flask import Flask, render_template, request, send_from_directory
from werkzeug.utils import secure_filename
from datetime import datetime
from transcricao import transcrever_com_diarizacao
from conversao import baixar_youtube

try:
    from googletrans import Translator
    HAS_TRANSLATOR = True
except ImportError:
    HAS_TRANSLATOR = False

import subprocess

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(PROJECT_DIR, "Uploads")
TRANSCRICOES_FOLDER = os.path.join(PROJECT_DIR, "Transcricoes")
CONVERSOES_FOLDER = os.path.join(PROJECT_DIR, "Conversoes")
ALLOWED_EXTENSIONS = {'mp3', 'mp4', 'wav', 'm4a', 'ogg', 'flac', 'webm', 'mkv'}

IDIOMAS = [
    ("auto", "Detectar automático"),
    ("pt", "Português"),
    ("en", "Inglês"),
    ("es", "Espanhol"),
    ("fr", "Francês"),
    ("de", "Alemão"),
]

# Perfis de conversão fixos
PERFIS_CONVERSAO = {
    "telefonia": {
        "label": "Telefonia (WAV 8kHz, mono)",
        "ext": "wav",
        "ffmpeg_args": ["-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le", "-af", "volume=3.0,highpass=f=300,lowpass=f=3400"],
    },
    "hq": {
        "label": "Alta Qualidade (FLAC 96kHz, 24bit)",
        "ext": "flac",
        "ffmpeg_args": ["-c:a", "flac", "-ar", "96000", "-bits_per_raw_sample", "24"],
    },
    "podcast": {
        "label": "Podcast (M4A, 192kbps)",
        "ext": "m4a",
        "ffmpeg_args": ["-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-af", "loudnorm"],
    },
    "streaming": {
        "label": "Streaming (OGG Vorbis, 48kHz)",
        "ext": "ogg",
        "ffmpeg_args": ["-c:a", "libvorbis", "-q:a", "6", "-ar", "48000"],
    },
    "radio": {
        "label": "Rádio FM (WAV 44kHz, estéreo)",
        "ext": "wav",
        "ffmpeg_args": ["-ar", "44100", "-ac", "2", "-acodec", "pcm_s16le", "-af", "acompressor=threshold=-16dB:ratio=4,volume=2"],
    },
    "whatsapp": {
        "label": "WhatsApp (OGG Opus, 128kbps)",
        "ext": "ogg",
        "ffmpeg_args": ["-c:a", "libopus", "-b:a", "128k", "-ar", "48000", "-af", "volume=1.5"],
    },
}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TRANSCRICOES_FOLDER, exist_ok=True)
os.makedirs(CONVERSOES_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def converter_audio_perfil(input_path, output_path, perfil_args):
    comando = ["ffmpeg", "-i", input_path] + perfil_args + ["-y", output_path]
    subprocess.run(comando, check=True)

@app.route('/')
def home():
    return render_template("home.html")

@app.route('/transcricao', methods=['GET', 'POST'])
def transcricao():
    transcricao = None
    filename = None
    filename_en = None
    error = None
    modelo = request.form.get("modelo", "small")
    idioma = request.form.get("idioma", "auto")
    if request.method == 'POST':
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            filename_local = secure_filename(file.filename)
            nome_base = os.path.splitext(filename_local)[0]
            nome_saida = f"transcricao_{nome_base}.txt"
            saida_path = os.path.join(TRANSCRICOES_FOLDER, nome_saida)
            try:
                filepath = os.path.join(UPLOAD_FOLDER, filename_local)
                file.save(filepath)
                texto = transcrever_com_diarizacao(filepath, modelo, idioma)
                with open(saida_path, "w", encoding="utf-8") as f:
                    f.write(texto)
                transcricao = texto
                filename = nome_saida

                nome_saida_en = f"transcricao_{nome_base}_ingles.txt"
                saida_path_en = os.path.join(TRANSCRICOES_FOLDER, nome_saida_en)
                if not os.path.exists(saida_path_en) and HAS_TRANSLATOR:
                    translator = Translator()
                    try:
                        traduzido = translator.translate(texto, src='pt', dest='en').text
                        with open(saida_path_en, "w", encoding="utf-8") as f:
                            f.write(traduzido)
                    except Exception as e:
                        print(f"Erro ao traduzir para inglês: {e}")
                if os.path.exists(saida_path_en):
                    filename_en = nome_saida_en
            except Exception as e:
                error = f"Erro na transcrição: {e}"
        else:
            error = "Arquivo inválido ou não suportado."
    return render_template(
        "transcricao.html",
        idiomas=IDIOMAS,
        transcricao=transcricao,
        filename=filename,
        filename_en=filename_en,
        error=error,
        modelo=modelo,
        idioma=idioma
    )

@app.route('/conversao', methods=['GET', 'POST'])
def conversao():
    resultado_conversao = None
    video_original = None
    error = None
    from_youtube = False
    if request.method == 'POST':
        file = request.files.get('file')
        youtube_link = request.form.get('youtube_link')
        perfil_key = request.form.get('perfil', 'telefonia')
        perfil = PERFIS_CONVERSAO.get(perfil_key, PERFIS_CONVERSAO["telefonia"])
        filename = None
        filepath = None
        if youtube_link and youtube_link.strip():
            from_youtube = True
            try:
                filename, filepath = baixar_youtube(youtube_link, UPLOAD_FOLDER)
                video_original = filename
                origem = os.path.join(UPLOAD_FOLDER, filename)
                destino = os.path.join(CONVERSOES_FOLDER, filename)
                if not os.path.exists(destino):
                    import shutil
                    shutil.copy2(origem, destino)
                video_original = filename
            except Exception as e:
                error = f"Erro ao baixar do YouTube: {e}"
        elif file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            video_original = filename
        else:
            error = "Arquivo inválido, não suportado ou link do YouTube ausente."
        if filepath and os.path.exists(filepath):
            try:
                nome_base = os.path.splitext(filename)[0] if filename else "arquivo"
                output_ext = perfil["ext"]
                output_name = f"{nome_base}_{perfil_key}.{output_ext}"
                output_path = os.path.join(CONVERSOES_FOLDER, output_name)
                converter_audio_perfil(filepath, output_path, perfil["ffmpeg_args"])
                resultado_conversao = output_name
            except Exception as e:
                error = f"Erro ao converter: {e}"
    return render_template(
        "conversao.html",
        resultado_conversao=resultado_conversao,
        video_original=video_original,
        error=error,
        from_youtube=from_youtube,
        perfis=PERFIS_CONVERSAO
    )

@app.route('/download/<path:filename>')
def download(filename):
    return send_from_directory(TRANSCRICOES_FOLDER, filename, as_attachment=True)

@app.route('/baixar_conversao/<path:filename>')
def baixar_conversao(filename):
    return send_from_directory(CONVERSOES_FOLDER, filename, as_attachment=True)

@app.route('/sobre')
def sobre():
    return render_template("sobre.html")

if __name__ == '__main__':
    port = int(os.environ.get('PORT',10000))
    app.run(debug = False, host= '0.0.0.0', port = port)