# This is a helper file for mathematical operations.
# It contains functions to perform basic arithmetic operations.

def add(x, y):
    """
    Add two numbers.
    
    Args:
    x (int/float): First number.
    y (int/float): Second number.
    
    Returns:
    int/float: Sum of x and y.
    """
    return x + y

def subtract(x, y):
    """
    Subtract two numbers.
    
    Args:
    x (int/float): First number.
    y (int/float): Second number.
    
    Returns:
    int/float: Difference of x and y.
    """
    return x - y

def multiply(x, y):
    """
    Multiply two numbers.
    
    Args:
    x (int/float): First number.
    y (int/float): Second number.
    
    Returns:
    int/float: Product of x and y.
    """
    return x * y

def divide(x, y):
    """
    Divide two numbers.
    
    Args:
    x (int/float): Dividend.
    y (int/float): Divisor.
    
    Returns:
    int/float: Quotient of x and y.
    """
    return x / y

# Example usage
print(add(5, 3))  # Output: 8
print(subtract(5, 3))  # Output: 2
print(multiply(5, 3))  # Output: 15
print(divide(5, 3))  # Output: 1.6666666666666667
