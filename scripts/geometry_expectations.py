"""Independent expected coordinates for reviewed historical geometry scenes."""
import math

def expected(case, t):
    r = math.sqrt(3)
    values = {
        "01": {"P": [-1, 1], "Q": [3, -3]},
        "08": {"B": [0, 6], "A": [2*r, 0], "C": [0, -6], "Ap": [2*r-t, 0], "Cp": [-t, -6]},
        "16": {"A": [-1, 0], "B": [3, 0], "C": [0, 3], "P": [t, -t*t+2*t+3], "M": [t, 3-t]},
        "21": {"A": [0, 4], "B": [-4, 0], "C": [4, 0], "D": [0, 0], "M": [0, math.sqrt(2)], "N": [4-math.sqrt(2), 4]},
        "28": {"B": [-2, 3], "Bs": [2, 3], "A": [t*t+t, 3]},
        "36": {"A": [1, 0], "C": [3, -4], "D": [3, 5], "E": [23/5, 9/5]},
        "41": {"A": [0, 2], "C": [0, 0], "E": [2, 0], "D": [2, 2], "G": [2, 2], "B": [3.2, 0], "F": [4, 2]},
        "48": {"A": [0, 0], "B": [-2*r, 0], "C": [0, 2], "Bp": [-2*r*math.cos(math.radians(t)), 2*r*math.sin(math.radians(t))], "Cp": [2*math.sin(math.radians(t)), 2*math.cos(math.radians(t))]},
        "56": {"A": [0, 0], "B": [8, 0], "C": [6*math.cos(t), 6*math.sin(t)], "D": [4+3*math.cos(t), 3*math.sin(t)], "E": [2*math.cos(t), 2*math.sin(t)]},
    }
    return values[case]

