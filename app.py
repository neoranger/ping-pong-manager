from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import math
import os

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
#app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///torneo.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'torneo.db')
db = SQLAlchemy(app)

UPLOAD_FOLDER = 'static/uploads/avatars'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# Asegurar que la carpeta exista
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Configuración de Login
app.config['SECRET_KEY'] = 'tu_llave_secreta_super_segura' # Cambia esto
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Limpiar metadatos existentes para evitar el error de duplicación
db.metadata.clear()

# Modelos
class Jugador(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    seleccionado = db.Column(db.Boolean, default=False)

class Equipo(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    jugador1_id = db.Column(db.Integer, db.ForeignKey('jugador.id'))
    jugador2_id = db.Column(db.Integer, db.ForeignKey('jugador.id'))

class Partido(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    id_local = db.Column(db.Integer) 
    id_visitante = db.Column(db.Integer)
    ronda = db.Column(db.Integer)
    ganador_id = db.Column(db.Integer, nullable=True)
    modo = db.Column(db.String(10))
    # Sets ganados (ej: 2 - 1)
    score_local = db.Column(db.Integer, default=0)
    score_visitante = db.Column(db.Integer, default=0)
    # Puntos detallados de cada set (ej: "11-5, 8-11, 11-9")
    puntos_detalle = db.Column(db.String(100), default="")

class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default='default_avatar.png') # Ruta de la imagen

with app.app_context():
    db.create_all()
    print("Base de datos verificada/creada con éxito.")

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

@app.route('/')
def index():
    jugadores = Jugador.query.all()
    equipos = Equipo.query.all()
    stats_jugadores = []

    for j in jugadores:
        # Partidos como Single
        singles = Partido.query.filter(
            ((Partido.id_local == j.id) | (Partido.id_visitante == j.id)),
            (Partido.modo == 'singles')
        ).count()

        # Partidos como Dobles (buscamos en qué equipos estuvo)
        mis_equipos = [e.id for e in equipos if e.jugador1_id == j.id or e.jugador2_id == j.id]
        dobles = Partido.query.filter(
            ((Partido.id_local.in_(mis_equipos)) | (Partido.id_visitante.in_(mis_equipos))),
            (Partido.modo == 'dobles')
        ).count()

        stats_jugadores.append({'obj': j, 'total': singles + dobles})
    # Diccionario maestro de nombres (IDs de jugadores + IDs de equipos)
    nombres = {j.id: j.nombre for j in jugadores}
    nombres.update({e.id: e.nombre for e in equipos}) # Añadimos los nombres de equipos
    partidos = Partido.query.all()
    return render_template('index.html', jugadores=stats_jugadores, partidos=partidos, nombres=nombres)

# --- ALTA (Con Validación) ---
@app.route('/registrar', methods=['POST'])
@login_required # Solo el admin puede registrar
def registrar():
    nombre = request.form.get('nombre').strip()
    if not nombre:
        return redirect(url_for('index'))

    # Validación: ¿Ya existe el jugador?
    existente = Jugador.query.filter_by(nombre=nombre).first()
    if existente:
        # Aquí podrías pasar un mensaje de error a la web
        return redirect(url_for('index'))

    nuevo_jugador = Jugador(nombre=nombre)
    db.session.add(nuevo_jugador)
    db.session.commit()
    return redirect(url_for('index'))

# --- BAJA ---
@app.route('/eliminar_jugador/<int:id>')
@login_required # Solo el admin puede borrar
def eliminar_jugador(id):
    jugador = Jugador.query.get(id)
    if jugador:
        # Nota: Al eliminar un jugador, sus partidos quedarían huérfanos.
        # Por ahora los borramos para mantener la integridad.
        Partido.query.filter((Partido.id_local == id) | (Partido.id_visitante == id)).delete()
        db.session.delete(jugador)
        db.session.commit()
    return redirect(url_for('index'))

# --- MODIFICACIÓN ---
@app.route('/editar_jugador/<int:id>', methods=['POST'])
@login_required
def editar_jugador(id):
    jugador = Jugador.query.get(id)
    nuevo_nombre = request.form.get('nuevo_nombre').strip()
    if jugador and nuevo_nombre:
        jugador.nombre = nuevo_nombre
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/marcar_ganador/<int:partido_id>', methods=['POST'])
@login_required
def marcar_ganador(partido_id):
    partido = Partido.query.get_or_404(partido_id)
    partido.score_local = int(request.form.get('s_local'))
    partido.score_visitante = int(request.form.get('s_vis'))
    partido.puntos_detalle = request.form.get('p_detalle') # Guardar puntos por set

    if partido.score_local > partido.score_visitante:
        partido.ganador_id = partido.id_local
    else:
        partido.ganador_id = partido.id_visitante

    db.session.commit()
    return redirect(url_for('index'))

@app.route('/crear_llaves/<modo>')
@login_required
def crear_llaves(modo):
    # 1. Obtener SOLO los que tienen el check verde
    jugadores_seleccionados = Jugador.query.filter_by(seleccionado=True).all()

    # 2. VALIDACIÓN CRÍTICA: Si no hay suficientes, abortar
    cant = len(jugadores_seleccionados)

    if modo == 'singles' and cant < 2:
        # Aquí podrías usar flash("Selecciona al menos 2 jugadores")
        return redirect(url_for('index'))

    if modo == 'dobles' and cant < 4:
        # Aquí podrías usar flash("Selecciona al menos 4 jugadores")
        return redirect(url_for('index'))

    # 3. Solo si pasa las validaciones, borramos el torneo anterior
    # Esto evita que borres un torneo que ya tenías si el nuevo falla por falta de gente
    Partido.query.delete()
    Equipo.query.delete()

    import random
    random.shuffle(jugadores_seleccionados)

    if modo == 'singles':
        for i in range(0, cant - 1, 2):
            nuevo_partido = Partido(
                id_local=jugadores_seleccionados[i].id,
                id_visitante=jugadores_seleccionados[i+1].id,
                ronda=1,
                modo='singles'
            )
            db.session.add(nuevo_partido)

    elif modo == 'dobles':
        # Solo hacemos parejas con grupos completos de 4
        # Si sobran 1, 2 o 3 jugadores, quedan fuera de la llave por seguridad
        for i in range(0, (cant // 4) * 4, 4):
            eq_a = Equipo(
                nombre=f"{jugadores_seleccionados[i].nombre} / {jugadores_seleccionados[i+1].nombre}",
                jugador1_id=jugadores_seleccionados[i].id,
                jugador2_id=jugadores_seleccionados[i+1].id
            )
            eq_b = Equipo(
                nombre=f"{jugadores_seleccionados[i+2].nombre} / {jugadores_seleccionados[i+3].nombre}",
                jugador1_id=jugadores_seleccionados[i+2].id,
                jugador2_id=jugadores_seleccionados[i+3].id
            )
            db.session.add(eq_a)
            db.session.add(eq_b)
            db.session.flush()

            nuevo_p = Partido(
                id_local=eq_a.id,
                id_visitante=eq_b.id,
                ronda=1,
                modo='dobles'
            )
            db.session.add(nuevo_p)

    db.session.commit()
    return redirect(url_for('index'))

# --- Lógica de Siguiente Ronda ---
@app.route('/avanzar_ronda')
@login_required
def avanzar_ronda():
    # 1. Buscamos la ronda actual más alta
    ultima_ronda = db.session.query(db.func.max(Partido.ronda)).scalar() or 1

    # 2. Obtenemos los partidos de esa ronda para saber el modo y los ganadores
    partidos_anteriores = Partido.query.filter_by(ronda=ultima_ronda).all()

    if not partidos_anteriores:
        return redirect(url_for('index'))

    # Detectamos el modo del torneo actual (asumimos que todos los de la ronda son iguales)
    modo_actual = partidos_anteriores[0].modo

    # 3. Recolectamos los IDs de los ganadores
    ganadores = [p.ganador_id for p in partidos_anteriores if p.ganador_id is not None]

    # Verificaciones de seguridad
    if len(ganadores) < 2:
        return redirect(url_for('index')) # No hay suficientes ganadores para emparejar

    if len(ganadores) != len(partidos_anteriores):
        return redirect(url_for('index')) # Aún faltan partidos por terminar en esta ronda

    # 4. Generamos los nuevos enfrentamientos para la Ronda + 1
    nueva_ronda = ultima_ronda + 1

    # Emparejamos a los ganadores de dos en dos
    for i in range(0, len(ganadores) - 1, 2):
        nuevo_partido = Partido(
            id_local=ganadores[i],
            id_visitante=ganadores[i+1],
            ronda=nueva_ronda,
            modo=modo_actual             # Mantenemos el modo (singles o dobles)
        )
        db.session.add(nuevo_partido)

    db.session.commit()
    return redirect(url_for('index'))

# --- Ruta para la Tabla de Posiciones ---
@app.route('/posiciones')
def posiciones():
    jugadores = Jugador.query.all()
    stats = []
    for j in jugadores:
        # Sumamos todos los sets a favor y en contra
        partidos_l = Partido.query.filter_by(id_local=j.id).all()
        partidos_v = Partido.query.filter_by(id_visitante=j.id).all()

        sets_f = sum([p.score_local for p in partidos_l]) + sum([p.score_visitante for p in partidos_v])
        sets_c = sum([p.score_visitante for p in partidos_l]) + sum([p.score_local for p in partidos_v])
        victorias = Partido.query.filter_by(ganador_id=j.id).count()

        stats.append({
            'nombre': j.nombre, 
            'victorias': victorias, 
            'sets_f': sets_f, 
            'sets_c': sets_c,
            'diferencia': sets_f - sets_c
        })

    # Ordenamos por victorias, y luego por diferencia de sets
    stats = sorted(stats, key=lambda x: (x['victorias'], x['diferencia']), reverse=True)
    return render_template('posiciones.html', stats=stats)

# --- Ruta para Reiniciar el Torneo ---
@app.route('/reset')
@login_required
def reset():
    # Borra todos los partidos de la base de datos
    Partido.query.delete()
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/posiciones_dobles')
def posiciones_dobles():
    equipos = Equipo.query.all()
    stats = []
    for e in equipos:
        victorias = Partido.query.filter_by(ganador_id=e.id, modo='dobles').count()
        stats.append({'nombre': e.nombre, 'victorias': victorias})

    stats = sorted(stats, key=lambda x: x['victorias'], reverse=True)
    return render_template('posiciones.html', stats=stats, titulo="Ranking de Dobles")

@app.route('/toggle_seleccion/<int:id>')
def toggle_seleccion(id):
    jugador = Jugador.query.get(id)
    if jugador:
        jugador.seleccionado = not jugador.seleccionado
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/limpiar_seleccion')
def limpiar_seleccion():
    # Ponemos a todos los jugadores en seleccionado = False
    Jugador.query.update({Jugador.seleccionado: False})
    db.session.commit()
    return redirect(url_for('index'))
    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = Usuario.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))
    
@app.route('/admin/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    if request.method == 'POST':
        user = Usuario.query.get(current_user.id)
        nuevo_username = request.form.get('username')

        # 1. Validar nombre de usuario antes de guardar
        if nuevo_username != user.username:
            existente = Usuario.query.filter_by(username=nuevo_username).first()
            if existente:
                # Si el nombre ya existe, puedes devolver un error o simplemente no cambiarlo
                return "Error: El nombre de usuario ya está en uso", 400
            user.username = nuevo_username
        
        # 2. Actualizar contraseña si se ingresó
        nueva_pass = request.form.get('password')
        if nueva_pass:
            user.password = generate_password_hash(nueva_pass)
            
        # 3. Manejar el Avatar (y borrar el viejo si existe)
        file = request.files.get('avatar')
        if file and file.filename != '':
            import os
            # Borrar foto vieja si no es la default
            if user.avatar != 'default_avatar.png':
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], user.avatar)
                if os.path.exists(old_path):
                    os.remove(old_path)

            filename = secure_filename(f"avatar_{user.id}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            user.avatar = filename
            
        db.session.commit()
        return redirect(url_for('index'))
        
    return render_template('perfil.html')
    
# --- Crear un administrador por defecto si no existe ---
with app.app_context():
    db.create_all()
    if not Usuario.query.filter_by(username='admin').first():
        hashed_pw = generate_password_hash('Encr1pt4d0', method='pbkdf2:sha256')
        admin = Usuario(username='admin', password=hashed_pw)
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
