from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import cv2
import numpy as np
import base64
import mysql.connector

from config import DB_CONFIG

from datetime import datetime
from deepface import DeepFace
from PIL import Image
from io import BytesIO



app = Flask(__name__)
app.secret_key = 'a4s4powerful'


# Connexion à la base de données MySQL
def connect_db():
    return mysql.connector.connect(**DB_CONFIG)

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Création du dossier uploads s’il n’existe pas
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def base64_to_opencv(image_base64):
    image_data = image_base64.split(',')[1]
    image_bytes = base64.b64decode(image_data)
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    return image

def extract_face_embedding(image):
    try:
        result = DeepFace.represent(
            image, model_name="Facenet", enforce_detection=False
        )[0]
        return np.array(result["embedding"], dtype=np.float32)
    except Exception as e:
        print("Erreur embedding :", str(e))
        return None

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']

        conn = connect_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE name = %s", (name,))
        user = cursor.fetchone()
        cursor.close()
        conn.close() 

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['name']
            session['role'] = user['role']
            return redirect(url_for('dashboard'))
        else:
            flash('Nom ou mot de passe incorrect.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        role = request.form['role']  # par exemple 'admin' ou 'agent'

        hashed_password = generate_password_hash(password)

        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (name, password, role) VALUES (%s, %s, %s)",
                       (name, hashed_password, role))
        conn.commit()
        cursor.close()
        conn.close()

        flash("Utilisateur enregistré avec succès.", "success")
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/profil', methods=['GET', 'POST'])
def profil():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    user_id = session['user_id']

    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    if request.method == 'POST':
        nouveau_nom = request.form['name']
        ancien_mdp = request.form['current_password']
        nouveau_mdp = request.form['password']
        confirm_mdp = request.form['confirm_password']

        if not check_password_hash(user['password'], ancien_mdp):
            flash("Ancien mot de passe incorrect", "danger")
        elif nouveau_mdp != confirm_mdp:
            flash("Les nouveaux mots de passe ne correspondent pas", "danger")
        else:
            hash_mdp = generate_password_hash(nouveau_mdp)
            cursor.execute("UPDATE users SET name=%s, password=%s WHERE id=%s", (nouveau_nom, hash_mdp, user_id))
            conn.commit()
            flash("Profil mis à jour avec succès", "success")
            session['username'] = nouveau_nom
            # Recharger les infos de l'utilisateur
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template('profil.html', user=user)

@app.route('/dashboard')
def dashboard():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    return render_template('dashboard.html')


@app.route('/recensement', methods=['GET', 'POST'])
def recensement():
    if request.method == 'GET':
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT nom FROM streets")
        avenues = cursor.fetchall()
        cursor.close()
        conn.close()

        conn = connect_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT nom FROM quarters")
        quartiers = cursor.fetchall()
        cursor.close()
        conn.close()

        return render_template('recensement.html', avenues=avenues, quartiers=quartiers)

    if 'image_base64' not in request.form:
        return 'Image manquante', 400

    try:
        image = base64_to_opencv(request.form['image_base64'])
        if image is None:
            return 'Image invalide', 400

        embedding = extract_face_embedding(image)
        if embedding is None:
            return 'Aucun visage détecté ou embedding échoué', 400

        # 🔁 Détection de doublon par similarité
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, nom, postnom, prenom, photo_encodee FROM citoyens")
        citoyens = cursor.fetchall()
        cursor.close()
        conn.close()

        for citoyen in citoyens:
            try:
                stored_embedding = np.frombuffer(citoyen['photo_encodee'], dtype=np.float32)
                similarity = np.linalg.norm(embedding - stored_embedding)
                if similarity < 10:  # Seuil identique à /verify
                    flash(f"⚠️ Doublon détecté : cette empreinte faciale a deja été enregistrée pour le citoyen : {citoyen['nom']} {citoyen['postnom']} {citoyen['prenom']}.", 'danger')
                    return redirect(url_for('recensement'))

            except Exception as e:
                print(f"Erreur vérification doublon ID {citoyen.get('id', '?')}: {str(e)}")
                continue

        # 📷 Sauvegarde de l’image
        filename = f"face_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        cv2.imwrite(file_path, image)

        nom_pere = request.form['nom_pere']
        nom_mere = request.form['nom_mere']
        date_naissance = request.form['date_naissance']
        annee_naissance = datetime.strptime(date_naissance, '%Y-%m-%d').year
        annee_actuelle = datetime.now().year
        age = str(annee_actuelle - annee_naissance)

        avenue = request.form['avenue']
        numero = request.form['numero']
        quartier = request.form['quartier']
        commune = request.form['commune']
        ville = request.form['ville']
        adresse_complete = f"{avenue}, {numero}/{quartier}/{commune}/{ville}"

        conn = connect_db()
        cursor = conn.cursor()
        sql = """
            INSERT INTO citoyens (
                nom, postnom, prenom, sexe, etat_civil, conjoint,
                adresse, contact, village, secteur, district, province,
                photo, photo_encodee, observation,
                nom_pere, nom_mere, date_naissance, age
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (
            request.form['nom'],
            request.form['postnom'],
            request.form['prenom'],
            request.form['sexe'],
            request.form['etat_civil'],
            request.form['conjoint'],
            adresse_complete,
            request.form['contact'],
            request.form['village'],
            request.form['secteur'],
            request.form['district'],
            request.form['province'],
            filename,
            embedding.tobytes(),
            request.form['observation'],
            nom_pere,
            nom_mere,
            date_naissance,
            age
        ))
        conn.commit()
        cursor.close()
        conn.close()

        flash('✅ Citoyen enregistré avec succès.')
        return redirect(url_for('recensement'))

    except Exception as e:
        return f"Erreur lors de l'enregistrement : {str(e)}", 500



@app.route('/manage_citoyens')
def manage_citoyens():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM citoyens")
    citoyens = cursor.fetchall()
    cursor.close()
    conn.close()

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT nom FROM streets")
    avenues = cursor.fetchall()
    cursor.close()
    conn.close()

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT nom FROM quarters")
    quartiers = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('manage_citoyens.html', citoyens=citoyens, avenues=avenues, quartiers=quartiers)

@app.route('/delete_citoyen/<int:id>')
def delete_citoyen(id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM citoyens WHERE id=%s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash("Citoyen supprimé.")
    return redirect(url_for('manage_citoyens'))

@app.route('/edit_citoyen/<int:id>', methods=['GET', 'POST'])
def edit_citoyen(id):
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':

        # Préparer les variables AVANT l'insertion
        nom_pere = request.form['nom_pere']
        nom_mere = request.form['nom_mere']
        date_naissance = request.form['date_naissance']
        annee_naissance = datetime.strptime(date_naissance, '%Y-%m-%d').year
        annee_actuelle = datetime.now().year
        age = str(annee_actuelle - annee_naissance)

        avenue = request.form['avenue']
        numero = request.form['numero']
        quartier = request.form['quartier']
        commune = request.form['commune']
        ville = request.form['ville']
        adresse_complete = f"{avenue}, {numero}/{quartier}/{commune}/{ville}"

        data = request.form
        cursor.execute("""
            UPDATE citoyens SET nom=%s, postnom=%s, prenom=%s, sexe=%s, etat_civil=%s, conjoint=%s,
            adresse=%s, contact=%s, village=%s, secteur=%s, district=%s, province=%s, observation=%s, 
            nom_pere=%s, nom_mere=%s, date_naissance=%s, age=%s
            WHERE id=%s
        """, (
            data['nom'], data['postnom'], data['prenom'], data['sexe'], data['etat_civil'], data['conjoint'],
            adresse_complete, data['contact'], data['village'], data['secteur'],
            data['district'], data['province'], data['observation'], nom_pere, nom_mere, date_naissance, age, id
        ))

        adresse_complete,
        nom_pere,
        nom_mere,
        date_naissance,
        age

        conn.commit() 
        flash("Citoyen modifié.")
        return redirect(url_for('manage_citoyens'))


    cursor.execute("SELECT * FROM citoyens WHERE id=%s", (id,))
    citoyen = cursor.fetchone()

    # EXTRACTION des composantes de l’adresse
    try:
        adresse_parts = citoyen['adresse'].split('/')
        avenue_num = adresse_parts[0].split(',')  # "Avenue X, 12"
        citoyen['avenue'] = avenue_num[0].strip()
        citoyen['numero'] = avenue_num[1].strip() if len(avenue_num) > 1 else ''
        citoyen['quartier'] = adresse_parts[1].strip() if len(adresse_parts) > 1 else ''
        citoyen['commune'] = adresse_parts[2].strip() if len(adresse_parts) > 2 else "N'sele"
        citoyen['ville'] = adresse_parts[3].strip() if len(adresse_parts) > 3 else "Kinshasa"
    except Exception as e:
        citoyen['avenue'] = ''
        citoyen['numero'] = ''
        citoyen['quartier'] = ''
        citoyen['commune'] = "N'sele"
        citoyen['ville'] = "Kinshasa"

    cursor.close()
    conn.close()

    cursor.execute("SELECT * FROM avenues")
    avenues = cursor.fetchall()

    cursor.execute("SELECT * FROM quartiers")
    quartiers = cursor.fetchall()

    return render_template('recensement.html', citoyen=citoyen, avenues=avenues, quartiers=quartiers)



@app.route('/manage_users')
def manage_users():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('manage_users.html', users=users)

@app.route('/update_user/<int:user_id>', methods=['POST'])
def update_user(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    name = request.form['name']
    role = request.form['role']

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('UPDATE users SET name = %s, role = %s WHERE id = %s', (name, role, user_id))
    conn.commit()
    cursor.close()
    conn.close()

    flash('Utilisateur modifié avec succès.', 'success')
    return redirect(url_for('manage_users'))

@app.route('/delete_user/<int:user_id>')
def delete_user(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('DELETE FROM users WHERE id = %s', (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

    flash('Utilisateur supprimé.', 'success')
    return redirect(url_for('manage_users'))

@app.route('/manage_street')
def manage_street():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM streets")
    streets = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('manage_street.html', streets=streets)

@app.route('/add_street', methods=['POST'])
def add_street():
    nom = request.form['nom']
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('INSERT INTO streets (nom) VALUES (%s)', (nom,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Avenue ajoutée avec succès.', 'success')
    return redirect(url_for('manage_street'))

@app.route('/update_street/<int:street_id>', methods=['POST'])
def update_street(street_id):
    nom = request.form['nom']
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('UPDATE streets SET nom = %s WHERE id = %s', (nom, street_id))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Avenue modifiée avec succès.', 'success')
    return redirect(url_for('manage_street'))

@app.route('/delete_street/<int:street_id>')
def delete_street(street_id):
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('DELETE FROM streets WHERE id = %s', (street_id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Avenue supprimée.', 'success')
    return redirect(url_for('manage_street'))

@app.route('/manage_quarters')
def manage_quarters():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM quarters")
    quarters = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('manage_quarters.html', quarters=quarters)

@app.route('/add_quarter', methods=['POST'])
def add_quarter():
    nom = request.form['nom']
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('INSERT INTO quarters (nom) VALUES (%s)', (nom,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Quartier ajouté avec succès.', 'success')
    return redirect(url_for('manage_quarters'))

@app.route('/update_quarter/<int:quarter_id>', methods=['POST'])
def update_quarter(quarter_id):
    nom = request.form['nom']
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('UPDATE quarters SET nom = %s WHERE id = %s', (nom, quarter_id))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Quartier modifié avec succès.', 'success')
    return redirect(url_for('manage_quarters'))

@app.route('/delete_quarter/<int:quarter_id>')
def delete_quarter(quarter_id):
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('DELETE FROM quarters WHERE id = %s', (quarter_id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Quartier supprimé.', 'success')
    return redirect(url_for('manage_quarters'))

@app.route('/verify', methods=['GET'])
def verify_form():
    return render_template('verify.html')

@app.route('/verify', methods=['POST'])
def verify():
    data = request.get_json()
    image_base64 = data.get('image_base64')

    if not image_base64:
        return jsonify({'found': False})

    image = base64_to_opencv(image_base64)
    input_embedding = extract_face_embedding(image)

    if input_embedding is None:
        return jsonify({'found': False})

    conn = connect_db()
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM citoyens")
        citoyens = cursor.fetchall()
    conn.close()

    for citoyen in citoyens:
        try:
            stored_embedding = np.frombuffer(citoyen['photo_encodee'], dtype=np.float32)
        except Exception as e:
            print(f"Erreur d'encodage pour l'ID {citoyen.get('id', '?')} : {e}")
            continue

        similarity = np.linalg.norm(input_embedding - stored_embedding)
        if similarity < 10:  # Seuil ajustable
            photo_path = os.path.join(UPLOAD_FOLDER, citoyen['photo'])
            photo_base64 = ""
            if os.path.exists(photo_path):
                with open(photo_path, "rb") as f:
                    photo_base64 = base64.b64encode(f.read()).decode('utf-8')

            return jsonify({
                'found': True,
                'nom': citoyen['nom'],
                'postnom': citoyen['postnom'],
                'prenom': citoyen['prenom'],
                'sexe': citoyen['sexe'],
                'etat_civil': citoyen['etat_civil'],
                'conjoint': citoyen['conjoint'],
                'adresse': citoyen['adresse'],
                'contact': citoyen['contact'],
                'village': citoyen['village'],
                'secteur': citoyen['secteur'],
                'district': citoyen['district'],
                'province': citoyen['province'],
                'nom_pere': citoyen['nom_pere'],
                'nom_mere': citoyen['nom_mere'],
                'date_naissance': citoyen['date_naissance'],
                'age': citoyen['age'],
                'photo': photo_base64
            })

    return jsonify({'found': False})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)

