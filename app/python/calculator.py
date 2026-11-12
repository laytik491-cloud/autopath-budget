import math
import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction


class ValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('Проверьте выделенные поля')


def decimal_text(value, minimum, maximum):
    text = str(value).strip().replace(',', '.')
    if len(text) > 30 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', text):
        raise ValueError('Введите число без букв и экспоненты')
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError('Введите корректное число')
    if not Decimal(str(minimum)) <= number <= Decimal(str(maximum)):
        raise ValueError(f'Введите число от {minimum} до {maximum}')
    whole, dot, fraction = text.partition('.')
    whole = str(int(whole))
    fraction = fraction.rstrip('0')
    return whole + ('.' + fraction if fraction else '')


def validate(parameters):
    result = {}
    errors = {}
    for field, minimum, maximum in [('consumption', '0.1', '100'), ('price', '0.01', '1000')]:
        try:
            result[field] = decimal_text(parameters.get(field, ''), minimum, maximum)
        except ValueError as error:
            errors[field] = str(error)
    participants = str(parameters.get('participants', '')).strip()
    if not re.fullmatch(r'[1-9]', participants):
        errors['participants'] = 'Введите целое число от 1 до 9'
    else:
        result['participants'] = int(participants)
    if errors:
        raise ValidationError(errors)
    return result


def format_fraction(value):
    value = Fraction(value)
    cents, remainder = divmod(value.numerator * 100, value.denominator)
    if remainder * 2 >= value.denominator:
        cents += 1
    return f'{cents // 100}.{cents % 100:02d}'


def calculate(distance_m, parameters):
    if isinstance(distance_m, bool) or not isinstance(distance_m, (int, float)) or not math.isfinite(distance_m) or distance_m <= 0:
        raise ValueError('Некорректное расстояние маршрута')
    return calculate_distance(Fraction(str(distance_m)) / 1000, parameters)


def calculate_manual(distance_km, parameters):
    distance = decimal_text(distance_km, '0.01', '1000000')
    return calculate_distance(Fraction(Decimal(distance)), parameters)


def calculate_distance(distance, parameters):
    data = validate(parameters)
    litres = distance * Fraction(Decimal(data['consumption'])) / 100
    total = litres * Fraction(Decimal(data['price']))
    share = total / data['participants']
    return {
        'distanceKm': format_fraction(distance),
        'litres': format_fraction(litres),
        'total': format_fraction(total),
        'perPerson': format_fraction(share)
    }
