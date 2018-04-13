"""Models and database functions for deep-paint"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from os import mkdir
from PIL import Image as PILImage
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import sys
sys.path.insert(0, 'fast-style-transfer')
import evaluate

db = SQLAlchemy()

FILESTORE_PATH = 'static/'
ALLOWED_EXTENSIONS = set(['gif', 'jpg', 'jpeg', 'png', 'tif', 'tga'])


# ========================================================================== #
# Mixins

class TimestampMixin(object):
    created_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow)


# ========================================================================== #
# Users

class User(TimestampMixin, db.Model):
    """User model

    Required fields:
        username          STRING(32) UNIQUE
        email             STRING(320) UNIQUE
        hashed_password   STRING(93)

    Optional fields:
        is_superuser      BOOLEAN
        pref_is_public    BOOLEAN
        pref_tf_model_id  INT REFERENCES tf_models
        pref_style_id     INT REFERENCES styles

    Additional attributes:
        user_id           SERIAL PRIMARY KEY
        created_at        DATETIME DEFAULT datetime.utcnow
        updated_at        DATETIME ONUPDATE datatime.utcnow
        styled_images     List of StyledImage objects
        source_images     List of SourceImage objects
        images            List of Image objects
        comments          List of Comment objects
        likes             List of Like objects
        pref_tf_model     TFModel object
        pref_style        Style object
    """

    __tablename__ = 'users'

    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                        nullable=False)
    username = db.Column(db.String(32), nullable=False, unique=True)
    email = db.Column(db.String(320), nullable=False, unique=True)
    hashed_password = db.Column(db.String(93), nullable=False)
    is_superuser = db.Column(db.Boolean, default=False, nullable=False)
    pref_is_public = db.Column(db.Boolean, default=True, nullable=False)
    pref_tf_model_id = db.Column(db.Integer,
                                 db.ForeignKey('tf_models.tf_model_id'))
    pref_style_id = db.Column(db.Integer, db.ForeignKey('styles.style_id'))

    pref_tf_model = db.relationship('TFModel', backref='users')
    pref_style = db.relationship('Style', backref='users')

    source_images = db.relationship('SourceImage', secondary='images')
    styled_images = db.relationship('StyledImage', secondary='images')

    def __repr__(self):
        return '<User user_id={id} username="{username}">'.format(
            id=self.user_id, username=self.username)

    def set_password(self, password):
        self.hashed_password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.hashed_password, password)

    @classmethod
    def create(cls, username, email, password, is_superuser=False):
        hashed_password = generate_password_hash(password)
        user = cls(username=username, email=email,
                   hashed_password=hashed_password, is_superuser=is_superuser)
        db.session.add(user)
        db.session.commit()
        mkdir(Image._path + '{id}'.format(id=user.user_id))
        return user

    @staticmethod
    def is_valid_email(email):
        """Check email for proper lengths and that @ and . symbols exist"""
        if len(email) > 320:
            return False

        at_index = email.find('@')
        if at_index == -1:
            return False

        local = email[:at_index]
        if len(local) > 64:
            return False

        domain = email[at_index+1:]
        if len(domain) > 255:
            return False

        dot_index = domain.find('.')
        if dot_index == 0 or dot_index == -1:
            return False

        return True


# ========================================================================== #
# Images

class Image(TimestampMixin, db.Model):
    """Base image model

    Optional fields:
        is_public       BOOLEAN
        user_id         INT REFERENCES users

    Additional attributes:
        image_id        SERIAL PRIMARY KEY
        created_at      DATETIME DEFAULT datetime.utcnow
        updated_at      DATETIME ONUPDATE datatime.utcnow
        user            User object

    Filename:
        {image_id}.{source_file_extension}

    File path for associated image:
        if user_id:
            {root_path}/image/{user_id}/{filename}
        else:
            {root_path}/image/misc/{filename}
    """

    __tablename__ = 'images'
    _path = FILESTORE_PATH + 'image/'

    image_id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                         nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    file_extension = db.Column(db.String(4), nullable=False)
    is_public = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship('User', backref='images')

    source_image = db.relationship('SourceImage', lazy='joined', uselist=False)
    styled_image = db.relationship('StyledImage', lazy='joined', uselist=False)

    def __repr__(self):
        return '<Image image_id={id} path="{path}">'.format(
            id=self.image_id, path=self.get_path())

    def get_path(self, modifier=None):
        """Return the file path for image instance"""
        if self.user_id:
            path = self._path + '{user_id}/'.format(user_id=self.user_id)
        else:
            path = self._path + 'misc/'
        filename = '{id}.{ext}'.format(id=self.image_id,
                                       ext=self.file_extension)
        if modifier:
            filename = modifier + filename
        return path + filename

    def get_thumbnail_path(self):
        """Return the thumbnail file path for image instance"""
        return self.get_path('thumb_')

    @classmethod
    def create(cls, image_file, user_id=None, is_public=True, resize=True):
        """Add an image to the database and save the image file"""
        if user_id:
            is_public = User.query.get(user_id).pref_is_public
        image = cls(user_id=user_id, is_public=is_public,
                    file_extension=cls.get_file_extension(image_file.filename))
        db.session.add(image)
        db.session.commit()

        image_file.save(image.get_path())
        if resize:
            Image.resize_image(image.get_path())

        return image

    @staticmethod
    def is_allowed_file(filename):
        """Verify the file is an image"""
        return ('.' in filename and
                Image.get_file_extension(filename) in ALLOWED_EXTENSIONS)

    @staticmethod
    def get_file_extension(filename):
        return filename.rsplit('.', 1)[1].lower()

    @staticmethod
    def resize_image(image_path, size=(1024, 1024)):
        image = PILImage.open(image_path)
        image.thumbnail(size, PILImage.LANCZOS)
        image.save(image_path)


class SourceImage(db.Model):
    """Source Image model

    Required fields:
        image_id         INT FOREGIN KEY images

    Optional fields:
        title            STRING(128)
        description      STRING(700)

    Additional attributes:
        source_image_id  SERIAL PRIMARY KEY
        styled_images    List of StyledImage objects
        image            Image object
        user             User object
    """

    __tablename__ = 'source_images'

    source_image_id = db.Column(db.Integer, primary_key=True,
                                autoincrement=True,
                                nullable=False)
    title = db.Column(db.String(128), default='', nullable=False)
    description = db.Column(db.String(700), default='', nullable=False)
    image_id = db.Column(db.Integer, db.ForeignKey('images.image_id'),
                         nullable=False)

    image = db.relationship('Image', lazy='joined', uselist=False)

    def __repr__(self):
        return '<SourceImage source_image_id={id} path="{path}">'.format(
            id=self.source_image_id, path=self.get_path())

    def get_path(self):
        return self.image.get_path()

    def get_thumbnail_path(self):
        return self.image.get_thumbnail_path()

    @classmethod
    def create(cls, image_file, user_id, title='', description=''):
        image = Image.create(image_file, user_id)
        source_image = cls(image_id=image.image_id, title=title,
                           description=description)
        db.session.add(source_image)
        db.session.commit()
        return source_image


class StyledImage(db.Model):
    """Styled Image model

    Required fields:
        image_id         INT REFERENCES images
        source_image_id  INT REFERENCES source_images
        style_id         INT REFERENCES styles

    Additional attributes:
        image            Image object
        source_image     SourceImage object
        style            Style object
        user             User object
    """

    __tablename__ = 'styled_images'

    styled_image_id = db.Column(db.Integer, primary_key=True,
                                autoincrement=True,
                                nullable=False)
    image_id = db.Column(db.Integer, db.ForeignKey('images.image_id'),
                         nullable=False)
    source_image_id = db.Column(db.Integer,
                                db.ForeignKey('source_images.source_image_id'),
                                nullable=False)
    style_id = db.Column(db.Integer, db.ForeignKey('styles.style_id'),
                         nullable=False)

    image = db.relationship('Image', lazy='joined', uselist=False)

    source_image = db.relationship('SourceImage', backref='styled_images')
    style = db.relationship('Style', backref='styled_images')

    def __repr__(self):
        return '<StyledImage styled_image_id={id} path="{path}">'.format(
            id=self.styled_image_id, path=self.get_path())

    def get_path(self):
        return self.image.get_path()

    def get_thumbnail_path(self):
        return self.image.get_thumbnail_path()

    @classmethod
    def create(cls, source_image_id, style_id):
        source_image = SourceImage.query.get(source_image_id)
        user = source_image.image.user
        style = Style.query.get(style_id)

        image = Image(user_id=user.user_id, is_public=user.pref_is_public,
                      file_extension=source_image.image.file_extension)
        db.session.add(image)
        db.session.commit()

        evaluate.ffwd_to_img(source_image.get_path(), image.get_path(),
                             style.get_path(), '/gpu:0')

        styled_image = cls(image_id=image.image_id,
                           source_image_id=source_image_id,
                           style_id=style_id)
        db.session.add(styled_image)
        db.session.commit()
        return styled_image


# ========================================================================== #
# TFModels & Styles

class TFModel(db.Model):
    """Tensorflow model

    Base tensorflow model from which Styles are derived

    Optional fields:
        title        STRING(128)
        description  STRING(700)

    Additional attributes:
        styles       List of Style objects
        users        List of User objects

    Filename:
        {tf_model_id}.mat

    Filepath:
        {root_path}/tf_model/{filename}
    """

    __tablename__ = 'tf_models'
    _path = FILESTORE_PATH + 'tf_model/'

    tf_model_id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                            nullable=False)
    title = db.Column(db.String(128), default='', nullable=False, unique=True)
    description = db.Column(db.String(700), default='', nullable=False)

    def __repr__(self):
        return '<TFModel tf_model_id={id} title="{title}">'.format(
            id=self.tf_model_id, title=self.title)

    def get_path(self):
        return self._path + '{id}.mat'.format(id=self.tf_model_id)

    @classmethod
    def create(cls, file, title='', description=''):
        tf_model = cls(title=title, description=description)
        db.session.add(tf_model)
        db.session.commit()
        file.save(tf_model.get_path())
        return tf_model


class Style(db.Model):
    """Style model

    Reference to tensorfolw checkpoint used for image styling

    Required fields:
        tf_model_id    INT REFERENCES tf_models
        image_id       INT REFERENCES images

    Optional fields:
        title          STRING(128)
        artist         STRING(128)
        description    STRING(700)

    Additional attributes:
        style_id       SERIAL PRIMARY KEY
        tf_model       TFModel object
        style          Style object
        image          Image object
        styled_images  StyledImage object
        users          List of User objects

    Filename:
        {style_id}.ckpt

    Filepath:
        {root_path}/style/{filename}
    """

    __tablename__ = 'styles'
    _path = FILESTORE_PATH + 'style/'

    style_id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                         nullable=False)
    title = db.Column(db.String(128), default='', nullable=False)
    artist = db.Column(db.String(128), default='', nullable=False)
    description = db.Column(db.String(700), default='', nullable=False)
    tf_model_id = db.Column(db.Integer, db.ForeignKey('tf_models.tf_model_id'),
                            nullable=False)
    image_id = db.Column(db.Integer, db.ForeignKey('images.image_id'),
                         nullable=False)

    tf_model = db.relationship('TFModel', backref='styles')
    image = db.relationship('Image', backref='styles')

    def __repr__(self):
        return '<Style style_id={id} title="{title}">'.format(
            id=self.style_id, title=self.title)

    def get_path(self):
        return self._path + '{id}.ckpt'.format(id=self.style_id)

    @classmethod
    def create(cls, style_file, image_file, tf_model_id, title='', artist='',
               description=''):
        image = Image.create(image_file)
        style = cls(tf_model_id=tf_model_id, image_id=image.image_id,
                    title=title, artist=artist, description=description)
        db.session.add(style)
        db.session.commit()
        style_file.save(style.get_path())
        return style


# ========================================================================== #
# Likes & Comments

class Comment(TimestampMixin, db.Model):
    """Comment model

    User comments on an image

    Tablename:
        comments

    Required fields:
        body        STRING(256)
        user_id     INT REFERENCES users
        image_id    INT REFERENCES images

    Additional attributes:
        comment_id  SERIAL PRIMARY KEY
        created_at  DATETIME DEFAULT datetime.utcnow
        updated_at  DATETIME ONUPDATE datatime.utcnow
        user        User object
        image       Image object
    """

    __tablename__ = 'comments'

    comment_id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                           nullable=False)
    body = db.Column(db.String(256), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'),
                        nullable=False)
    image_id = db.Column(db.Integer, db.ForeignKey('images.image_id'),
                         nullable=False)

    user = db.relationship('User', backref='comments')
    image = db.relationship('Image', backref='comments')

    def __repr__(self):
        return '<Comment comment_id={id} body="{body}">'.format(
            id=self.comment_id, body=self.body)

    def __str__(self):
        return self.body


class Like(db.Model):
    """Like model

    User likes on an image

    Tablename:
        likes

    Required fields:
        user_id   INT PRIMARY KEY REFERENCES users
        image_id  INT PRIMARY KEY REFERENCES images
        users     List of User objects
        images    List of Image objects
    """

    __tablename__ = 'likes'

    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'),
                        primary_key=True, nullable=False)
    image_id = db.Column(db.Integer, db.ForeignKey('images.image_id'),
                         primary_key=True, nullable=False)

    user = db.relationship('User', backref='likes')
    images = db.relationship('Image', backref='likes')

    def __repr__(self):
        return '<Like user_id={user} image_id={image}>'.format(
            user=self.user_id, image=self.image_id)


# ========================================================================== #
# Tags

class Tag(db.Model):
    """Tag model

    User configured image category

    Tablename:
        tags

    Required fields:
        name    STRING(32)

    Additional attributes:
        tag_id  SERIAL PRIMARY KEY
        images  List of Image objects
    """

    __tablename__ = 'tags'

    tag_id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                       nullable=False)
    name = db.Column(db.String(32), nullable=False, unique=True)

    images = db.relationship('Image', secondary='image_tags', backref='tags')

    def __repr__(self):
        return '<Tag tag_id={id} name="{name}">'.format(
            id=self.tag_id, name=self.name)

    def __str__(self):
        return self.name


class ImageTag(db.Model):
    """ImageTag association table model

    Tablename:
        image_tags

    Required fields:
        tag_id    INT PRIMARY KEY REFERENCES tags
        image_id  INT PRIMARY KEY REFERENCES images
    """

    __tablename__ = 'image_tags'

    tag_id = db.Column(db.Integer, db.ForeignKey('tags.tag_id'),
                       primary_key=True)
    image_id = db.Column(db.Integer, db.ForeignKey('images.image_id'),
                         primary_key=True)


# ========================================================================== #
# Helper functions

def connect_to_db(app):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'postgres:///deep-paint'
    db.app = app
    db.init_app(app)


def seed_data():
    tf_file = FileStorage(stream=open(
        'fast-style-transfer/models/imagenet-vgg-verydeep-19.mat'))
    tf = TFModel.create(file=tf_file, title='fast-style-transfer',
                        description='Created by Logan Engstrom')

    muse_file = FileStorage(stream=open('fast-style-transfer/styles/muse.ckpt'))
    muse_image = FileStorage(stream=open('fast-style-transfer/styles/muse.jpg'))
    muse_style = Style.create(style_file=muse_file,
                              image_file=muse_image,
                              tf_model_id=tf.tf_model_id,
                              title='La Muse',
                              artist='Pablo Picasso',
                              description="This painting is also known as Young Woman Drawing and Two Women. It's a story of two women. One sits, copying what she sees in the mirror set up in front of her; the other sleeps with her head in her arms.\nThere was a series of paintings Picasso did at this time of young women drawing, writing or reading. This is Marie Therese Walther not with the rounded, ample forms the painter normally used to depict her but with an angular style. The sleeping girl resembles her as well, and indeed she would be somewhere (anywhere's better than nowhere) in Picasso's affections for some years to come. Maia, their daughter was born a few months after this was painted, in October 1935."
                              )

    rain_file = FileStorage(stream=open('fast-style-transfer/styles/rain.ckpt'))
    rain_image = FileStorage(stream=open('fast-style-transfer/styles/rain.jpg'))
    rain_style = Style.create(style_file=rain_file,
                              image_file=rain_image,
                              tf_model_id=tf.tf_model_id,
                              title='Rain Princess',
                              artist='Leonid Afremov',
                              description="Rain Princess is a painting by Leonid Afremov which was uploaded on February 17th, 2014.\nYou can buy this painting from his official shop via this link: https://www.etsy.com/listing/16654120"
                              )

    scream_file = FileStorage(stream=open('fast-style-transfer/styles/scream.ckpt'))
    scream_image = FileStorage(stream=open('fast-style-transfer/styles/scream.jpg'))
    scream_style = Style.create(style_file=scream_file,
                                image_file=scream_image,
                                tf_model_id=tf.tf_model_id,
                                title='The Scream',
                                artist='Edvard Munch',
                                description="Munch's The Scream is an icon of modern art, the Mona Lisa for our time. As Leonardo da Vinci evoked a Renaissance ideal of serenity and self-control, Munch defined how we see our own age - wracked with anxiety and uncertainty."
                                )

    udnie_file = FileStorage(stream=open('fast-style-transfer/styles/udnie.ckpt'))
    udnie_image = FileStorage(stream=open('fast-style-transfer/styles/udnie.jpg'))
    udnie_style = Style.create(style_file=udnie_file,
                               image_file=udnie_image,
                               tf_model_id=tf.tf_model_id,
                               title='Udnie',
                               artist='Francis Picabia',
                               description="Udnie was inspired by a dance performance given by the Polish-born actress Stacia Napierkowska on the boat taking Francis Picabia to New York for the Armory Show in 1913. The work combines the decomposition of volumes into planes characteristic of Cubism with the enthusiasm for a world in movement of Italian Futurism. The energy and vitality of the dance find expression in springing arabesque, fragmented coloured planes and the jostling of simplified forms. In the radicalism of its treatment, Udnie marks a decisive step towards the emergence of abstraction in Europe."
                               )

    wave_file = FileStorage(stream=open('fast-style-transfer/styles/wave.ckpt'))
    wave_image = FileStorage(stream=open('fast-style-transfer/styles/wave.jpg'))
    wave_style = Style.create(style_file=wave_file,
                              image_file=wave_image,
                              tf_model_id=tf.tf_model_id,
                              title='Under the Wave off Kanagawa',
                              artist='Katsushika Hokusai',
                              description="Katsushika Hokusai's Under the Wave off Kanagawa, also called The Great Wave has became one of the most famous works of art in the world-and debatably the most iconic work of Japanese art. Initially, thousands of copies of this print were quickly produced and sold cheaply. Despite the fact that it was created at a time when Japanese trade was heavily restricted, Hokusai's print displays the influence of Dutch art, and proved to be inspirational for many artists working in Europe later in the nineteenth century."
                              )

    wreck_file = FileStorage(stream=open('fast-style-transfer/styles/wreck.ckpt'))
    wreck_image = FileStorage(stream=open('fast-style-transfer/styles/wreck.jpg'))
    wreck_style = Style.create(style_file=wreck_file,
                               image_file=wreck_image,
                               tf_model_id=tf.tf_model_id,
                               title='The Shipwreck of the Minotaur',
                               artist='Joseph Mallord William Turner',
                               description="Shipwreck may be regarded as one of the worst things a human being can encounter. The sea is no respecter of persons- instantly, 100s of men can be wiped out. Turner's fascination with man vs. nature is display in The Shipwreck. He wished to portray the power of the elements and how no one is immune from the dangers of an angry sea; he can struggle and fight but ultimately he will be swallowed up by the sea. The unlikelihood of deliverance from such calamity is great."
                               )

    user = User.create(username='TestUser', email='estrella+dptest@evinc.es',
                       password='faketestpassword')

    user_image = FileStorage(stream=open('in/IMG_20171005_112709.jpg'))
    source_image = SourceImage.create(image_file=user_image,
                                      user_id=user.user_id,
                                      title="Wooden Path in Sunlight",
                                      description="Taken at Cape Flattery, WA on a sunny day in October, 2017.")


if __name__ == "__main__":
    from flask import Flask
    app = Flask(__name__)

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ECHO'] = True
    connect_to_db(app)

    db.create_all()
    # seed_data()
