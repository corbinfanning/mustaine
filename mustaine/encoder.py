import datetime
import time
from struct import pack
import binascii

from mustaine.protocol import *

# Implementation of Hessian 1.0.2 serialization
#   see: http://hessian.caucho.com/doc/hessian-1.0-spec.xtp

ENCODERS = {}
def encoder_for(data_type):
    def register(f):
        # register function `f` to encode type `data_type`
        ENCODERS[data_type] = f
        return f
    return register

def returns(data_type):
    def wrap(f):
        # wrap function `f` to return a tuple of (type,data)
        def wrapped(*args):
            return data_type, f(*args)
        return wrapped
    return wrap

def encode_object(obj):
    if type(obj) in ENCODERS:
        encoder = ENCODERS[type(obj)]
    else:
        raise TypeError("mustaine.encoder cannot serialize %s" % (type(obj),))

    return encoder(obj)[1]


@encoder_for(None)
@returns('null')
def encode_null(_):
    return 'N'

@encoder_for(bool)
@returns('bool')
def encode_boolean(value):
    if value:
        return 'T'
    else:
        return 'F'

@encoder_for(int)
@returns('int')
def encode_int(value):
    return pack('>cl', b'I', value)

@encoder_for(int)
@returns('long')
def encode_long(value):
    return pack('>cq', b'L', value)

@encoder_for(float)
@returns('double')
def encode_double(value):
    return pack('>cd', b'D', value)

@encoder_for(datetime.datetime)
@returns('date')
def encode_date(value):
    return pack('>cq', b'd', int(time.mktime(value.timetuple())) * 1000)

@encoder_for(str)
@returns('string')
def encode_string(value):
    encoded = ''

    try:
        value = value.encode('ascii')
    except UnicodeDecodeError:
        raise TypeError("mustaine.encoder cowardly refuses to guess the encoding for "
                        "string objects containing bytes out of range 0x00-0x79; use "
                        "Binary or unicode objects instead")

    while len(value) > 65535:
        encoded += pack('>cH', 's', 65535)
        encoded += value[:65535]
        value = value[65535:]

    encoded += pack('>cH', b'S', len(value.decode('utf-8')))
    encoded += value
    return encoded

@encoder_for(str)
@returns('string')
def encode_unicode(value):
    encoded = ''

    while len(value) > 65535:
        encoded += pack('>cH', b's', 65535)
        encoded += value[:65535].encode('utf-8')
        value    = value[65535:]

    encoded += pack('>cH', b'S', len(value))
    encoded += value.encode('utf-8')
    return encoded

@encoder_for(list)
@returns('list')
def encode_list(obj):
    encoded = ''.join(map(encode_object, obj))
    return pack('>2cl', b'V', b'l', -1) + str.encode(encoded) + b'z'

@encoder_for(tuple)
@returns('list')
def encode_tuple(obj):
    encoded = ''.join(map(encode_object, obj))
    return pack('>2cl', b'V', b'l', len(obj)) + str.encode(encoded) + b'z'

def encode_keyval(pair):
    return ''.join((encode_object(pair[0]), encode_object(pair[1])))

@encoder_for(dict)
@returns('map')
def encode_map(obj):
    encoded = ''.join(map(encode_keyval, obj.items()))
    return pack('>c', b'M') + str.encode(encoded) + b'z'

@encoder_for(Object)
def encode_mobject(obj):
    encoded  = pack('>cH', b't', len(obj._meta_type)) + obj._meta_type
    members  = obj.__getstate__()
    del members['__meta_type'] # this is here for pickling. we don't want or need it

    encoded += ''.join(map(encode_keyval, members.items()))
    return (obj._meta_type.rpartition('.')[2], pack('>c', b'M') + encoded + b'z')

@encoder_for(Remote)
@returns('remote')
def encode_remote(obj):
    encoded = encode_string(obj.url)
    return pack('>2cH', 'r', 't', len(obj.type_name)) + obj.type_name + encoded

@encoder_for(Binary)
@returns('binary')
def encode_binary(obj):
    encoded = ''
    value   = obj.value

    while len(value) > 65535:
        encoded += pack('>cH', b'b', 65535)
        encoded += value[:65535]
        value    = value[65535:]

    encoded += pack('>cH', b'B', len(value))
    encoded += value

    return encoded

@encoder_for(Call)
@returns('call')
def encode_call(call):
    method    = call.method
    headers   = ''
    arguments = ''

    for header,value in call.headers.items():
        if not isinstance(header, str):
            raise TypeError("Call header keys must be strings")

        headers += pack('>cH', 'H', len(header)) + str.encode(header)
        headers += encode_object(value)

    # TODO: this is mostly duplicated at the top of the file in encode_object. dedup
    for arg in call.args:
        if type(arg) in ENCODERS:
            encoder = ENCODERS[type(arg)]
        else:
            raise TypeError("mustaine.encoder cannot serialize %s" % (type(arg),))

        data_type, arg = encoder(arg)
        if call.overload:
            method += '_' + data_type
        arguments += arg.decode()

    encoded  = pack('>cBB', b'c', 1, 0).decode()
    encoded += str.encode(headers)
    encoded += pack('>cH', b'm', len(method)) + str.encode(method)
    encoded += str.encode(arguments)
    encoded += b'z'

    return encoded

