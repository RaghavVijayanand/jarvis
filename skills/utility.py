import ast
import math
import operator
import random
import re
import secrets
import string

class UtilitySkill:
    def __init__(self):
        self.jokes = [
            "Why don't scientists trust atoms? Because they make up everything!",
            "I told my wife she was drawing her eyebrows too high. She looked surprised.",
            "Why don't eggs tell jokes? They'd crack each other up!",
            "What do you call a fake noodle? An impasta!",
            "Why did the scarecrow win an award? He was outstanding in his field!",
            "What do you call a bear with no teeth? A gummy bear!",
            "Why don't skeletons fight each other? They don't have the guts!",
            "What's the best thing about Switzerland? I don't know, but the flag is a big plus!",
            "How do you organize a space party? You planet!",
            "Why did the math book look so sad? Because it had too many problems!"
        ]

    def tell_joke(self):
        """Tell a random joke"""
        return random.choice(self.jokes)
    
    _MATH_WORDS = [
        (r"\bto the power of\b|\braised to(?: the power of)?\b|\^", "**"),
        (r"\bmultiplied by\b|\btimes\b|×|(?<=\d)\s*x\s*(?=[\d(])|\bx\b(?=\s*\d)", "*"),
        (r"\bdivided by\b|\bover\b|÷", "/"),
        (r"\bplus\b", "+"), (r"\bminus\b", "-"),
        (r"\bsquared\b", "**2"), (r"\bcubed\b", "**3"), (r"\bmod(?:ulo)?\b", "%"),
    ]
    _FUNCS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
              "log": math.log10, "ln": math.log, "abs": abs, "round": round}
    _CONSTS = {"pi": math.pi, "e": math.e}
    _BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
               ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
               ast.Pow: operator.pow}
    _UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
    _MAX_BITS = 14_000        # ~4,200 digits (Python refuses to print >4,300)
    _MAX_INPUT = 200

    class _Unsafe(ValueError):
        """Expression uses syntax outside plain arithmetic."""

    def _eval_node(self, node):
        """Evaluate a whitelisted arithmetic AST.  No names, attributes,
        subscripts, containers or strings can be reached, and every
        intermediate integer is size-capped so '9**9**9' or '(9**9999)**9999'
        cannot hang or exhaust memory."""
        if isinstance(node, ast.Expression):
            return self._eval_node(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.Name) and node.id in self._CONSTS:
            return self._CONSTS[node.id]
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._UNARY:
            return self._check(self._UNARY[type(node.op)](self._eval_node(node.operand)))
        if isinstance(node, ast.BinOp) and type(node.op) in self._BINOPS:
            left, right = self._eval_node(node.left), self._eval_node(node.right)
            if isinstance(node.op, ast.Pow):
                if abs(right) > 10_000 and abs(left) not in (0, 1):
                    raise OverflowError("result too large")
                if isinstance(left, int) and isinstance(right, int) and right > 0 and abs(left) > 1:
                    if right * math.log2(abs(left)) > self._MAX_BITS:
                        raise OverflowError("result too large")
            return self._check(self._BINOPS[type(node.op)](left, right))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in self._FUNCS
                and not node.keywords and len(node.args) <= 2):
            args = [self._eval_node(a) for a in node.args]
            if node.func.id == "round" and len(args) == 2:
                args[1] = int(args[1])
            return self._check(self._FUNCS[node.func.id](*args))
        raise self._Unsafe(type(node).__name__)

    def _check(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self._Unsafe("non-numeric result")
        if isinstance(value, int) and value.bit_length() > self._MAX_BITS:
            raise OverflowError("result too large")
        return value

    def calculate(self, expression):
        """Safely evaluate arithmetic, including phrases like '15% of 200' or 'square root of 81'.

        User text is never passed to eval/exec: it is parsed with ``ast`` and
        only numeric literals, + - * / // % **, pi/e and a few math functions
        are evaluated."""
        failure = f"Could not calculate '{expression}'. Please check your syntax."
        try:
            text = str(expression).lower().strip().rstrip("?.! =")
            text = re.sub(r"^(?:what(?:'s|s| is)|calculate|calc|compute|solve|evaluate|how much is|tell me)\s+", "", text)
            text = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)", r"(\1/100*\2)", text)
            text = re.sub(r"\b(?:the\s+)?square root of\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", text)
            text = re.sub(r"\b(?:the\s+)?cube root of\s*(\d+(?:\.\d+)?)", r"(\1**(1/3))", text)
            for pattern, repl in self._MATH_WORDS:
                text = re.sub(pattern, repl, text)
            text = re.sub(r"\bthe\b", " ", text)
            text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)   # 1,000 -> 1000 (keep round(x, 2))
            text = text.strip()
            if not re.search(r"\d", text) or len(text) > self._MAX_INPUT:
                return failure
            result = self._eval_node(ast.parse(text, mode="eval"))
            if isinstance(result, float):
                if math.isinf(result) or math.isnan(result):
                    return "Error: The result is too large to calculate."
                result = int(result) if result.is_integer() else round(result, 10)
            shown = re.sub(r"^(?:what(?:'s|s| is)|calculate|calc|compute|solve|evaluate|how much is|tell me)\s+", "",
                           str(expression).strip(), flags=re.I).rstrip("?=. ")
            return f"{shown} = {result}"
        except ZeroDivisionError:
            return "Error: Division by zero"
        except OverflowError:
            return "Error: The result is too large to calculate."
        except Exception:
            return failure

    def generate_password(self, length=12, include_symbols=True):
        """Generate a secure password"""
        
        try:
            length = int(length)
            if length < 4:
                length = 8
            elif length > 50:
                length = 50
            
            chars = string.ascii_letters + string.digits
            if include_symbols:
                chars += "!@#$%^&*"
            
            # secrets, not random: passwords must come from a CSPRNG.
            password = ''.join(secrets.choice(chars) for _ in range(length))
            return f"Generated password: {password}"
            
        except Exception as e:
            return f"Error generating password: {e}"
    
    def flip_coin(self):
        """Flip a coin"""
        result = random.choice(["Heads", "Tails"])
        return f"Coin flip result: {result}"
    
    def roll_dice(self, sides=6, count=1):
        """Roll dice"""
        try:
            sides = int(sides)
            count = int(count)
            
            if sides < 2:
                sides = 6
            if count < 1 or count > 10:
                count = 1
            
            results = [random.randint(1, sides) for _ in range(count)]
            
            if count == 1:
                return f"Rolled a {sides}-sided die: {results[0]}"
            else:
                total = sum(results)
                return f"Rolled {count} {sides}-sided dice: {results} (Total: {total})"
                
        except Exception as e:
            return f"Error rolling dice: {e}"
    
    def get_random_number(self, min_val=1, max_val=100):
        """Generate a random number within range"""
        try:
            min_val = int(min_val)
            max_val = int(max_val)
            
            if min_val > max_val:
                min_val, max_val = max_val, min_val
            
            result = random.randint(min_val, max_val)
            return f"Random number between {min_val} and {max_val}: {result}"
            
        except Exception as e:
            return f"Error generating random number: {e}"
