import math
def digit_counter(n:int):
        i = int(math.log10(n) + 1)
        return i


N = int(input("Enter the number: "))
print(digit_counter(N))