#!/usr/bin/env python3
"""
Demo of the improved Depictio logo with brand colors.
This version uses updated ASCII art with unique character patterns for each distinct triangle to ensure granular coloring.
"""

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Depictio brand colors from depictio/dash/colors.py
DEPICTIO_COLORS = {
    "purple": "#9966CC",
    "violet": "#7A5DC7",
    "blue": "#6495ED",
    "teal": "#45B8AC",
    "green": "#8BC34A",
    "yellow": "#F9CB40",
    "orange": "#F68B33",
    "pink": "#E6779F",
    "red": "#E53935",
    "black": "#000000",
}

def create_final_depictio_logo():
    """Create the final Depictio logo with a unique color for each distinct triangle."""

    # The ASCII art has been updated to use a unique character for each visually distinct triangle.
    FAVICON_ASCII_FINAL = """
                                   .=AAAAABBBB=-:.
                                   .=AAAAAAAAAAA=-:.
                                   .=AAAAAAAAAAAAACCC=-
                                   .=AAAAAAAAAAAAAAAAA=-:.
                             .==.  .=AAAAAAAAAAAAAAAAAAAA-
                      .:-=+DDDD+:  .=AAAAAAAAAAAAAAAAAA-.
                   .-++DDDDDDDD+:  .=AAAAAAAAAAAAAAAA-.
                 .-+DDDDDDDDDDD+:  .=AAAAAAAAAAAAAA-.
                 .-+DDDDDDDDDDD+:  .=AAAAAAAAAAAA=.
                   .-+DDDDDDDDDD+:  .=AAAAAAAAAA-.  :=-.
                     .-+DDDDDDDD+:  .=AAAAAAAA=. .:=EEEE-.
                       .-+DDDDD+:  .=AAAAAA=.  .=EEEEEEE-.
                         .-+DDD+:  .=AAAA=.  :=EEEEEEEEEE-.
                   .=FGF-. .-+D+:  .=AA=.  .=GGGGGGGGGGGG=-:
                  .-HIIIIH-. .==:  .==:  .=GGGGGGGGGGGGGG=:.
                  .=JKKKKKKJ-:.        :=AAAAAAAAAAAAAAAAAAA
                   :-=------=-        .:--::::::::::::::::--

=============================-        :==+==================
LLLLLLLLLLLLLLLLLLLLLLLLLLL+:....   .. :+LLLLLLLLLLLLLLLLLLMM
DDDDDDDDDDDDDDDDDDDDDDDDDL+:. :NN-. .NO-. .+LLLLLLLLLLLLLLLD=-
DDDDDDDDDDDDDDDDDDDDDDDL+:  .+PQP:.  .PQQP-. .+LLLLLLLLLLLLD-:
:-LDDDDDDDDDDDDDDDDDDDL+:. .+PRRR:.  .PRRRRP-. :+LLLLLLLLLL+:.
:-+LDDDDDDDDDDDDDDDL+-. .+PSTSP:.  .PSTTTTP:.  :+LLLLLLD+-
  =DLDDDDDDDDDDDL+-. .+PUUVUUU:.  .PUUUUP=.     :+LLLUU-
  -+DLDDDDDDDDDL+-. .+PWWXWWWWU:.  .++-..          :=+=:
   :DULLDDDDLD-. .+PWWXXXXXWWU-
    .-DLDDLD-.   .=KXXXXDDDDDL-
      :=DD-.       .=DLLXXXKKL-
       .:.            .:=DLXXX-
"""

    # Each new character is mapped to a distinct brand color.
    color_map = {
        'A': DEPICTIO_COLORS['yellow'],
        'B': DEPICTIO_COLORS['red'],
        'C': DEPICTIO_COLORS['pink'],
        'D': DEPICTIO_COLORS['red'],
        'E': DEPICTIO_COLORS['yellow'],
        'F': DEPICTIO_COLORS['purple'],
        'G': DEPICTIO_COLORS['yellow'],
        'H': DEPICTIO_COLORS['purple'],
        'I': DEPICTIO_COLORS['blue'],
        'J': DEPICTIO_COLORS['blue'],
        'K': DEPICTIO_COLORS['green'],
        'L': DEPICTIO_COLORS['purple'],
        'M': DEPICTIO_COLORS['blue'],
        'N': DEPICTIO_COLORS['red'],
        'O': DEPICTIO_COLORS['purple'],
        'P': DEPICTIO_COLORS['blue'],
        'Q': DEPICTIO_COLORS['green'],
        'R': DEPICTIO_COLORS['orange'],
        'S': DEPICTIO_COLORS['pink'],
        'T': DEPICTIO_COLORS['yellow'],
        'U': DEPICTIO_COLORS['violet'],
        'V': DEPICTIO_COLORS['teal'],
        'W': DEPICTIO_COLORS['green'],
        'X': DEPICTIO_COLORS['orange'],
        '=': DEPICTIO_COLORS['teal'],
        '-': DEPICTIO_COLORS['green'],
        ':': DEPICTIO_COLORS['violet'],
        '.': DEPICTIO_COLORS['orange']
    }

    logo = Text()

    for line in FAVICON_ASCII_FINAL.split('\n'):
        for char in line:
            if char in color_map:
                logo.append(char, style=f"{color_map[char]} bold")
            else:
                logo.append(char)  # For spaces and other characters
        logo.append('\n')

    return logo

def create_depictio_text_logo():
    """Create a colorful DEPICTIO text using brand colors."""
    logo = Text()

    # Each letter gets a different brand color
    letters_colors = [
        ('D', DEPICTIO_COLORS['purple']),
        ('E', DEPICTIO_COLORS['violet']),
        ('P', DEPICTIO_COLORS['blue']),
        ('I', DEPICTIO_COLORS['teal']),
        ('C', DEPICTIO_COLORS['green']),
        ('T', DEPICTIO_COLORS['yellow']),
        ('I', DEPICTIO_COLORS['orange']),
        ('O', DEPICTIO_COLORS['red'])
    ]

    for letter, color in letters_colors:
        logo.append(letter, style=f"{color} bold")

    logo.append(" CLI", style=f"{DEPICTIO_COLORS['black']} bold")
    return logo

def demo_final_logo():
    """Demo the final logo in different styles."""
    console = Console()

    # ASCII Logo only
    console.print("\n[bold]Final Logo with Unique Colors per Triangle:[/bold]")
    ascii_logo = create_final_depictio_logo()
    console.print(Panel.fit(
        Align.center(ascii_logo),
        border_style=DEPICTIO_COLORS['purple'],
        title="✨ Depictio CLI ✨",
        title_align="center",
        padding=(1, 2)
    ))

    # Text Logo
    console.print("\n[bold]Colorful Text Logo:[/bold]")
    text_logo = create_depictio_text_logo()
    console.print(Panel.fit(
        Align.center(text_logo),
        border_style=DEPICTIO_COLORS['teal'],
        title="Welcome",
        title_align="center"
    ))

    # Combined
    console.print("\n[bold]Combined Version:[/bold]")
    combined_content = Text()
    combined_content.append_text(ascii_logo)
    combined_content.append("\n\n")
    combined_content.append_text(Align.center(text_logo))

    console.print(Panel.fit(
        Align.center(combined_content),
        border_style=DEPICTIO_COLORS['blue'],
        title="✨ Welcome to Depictio CLI ✨",
        title_align="center",
        padding=(1, 2)
    ))

def get_cli_integration_code():
    """Returns the updated code snippet to integrate into your CLI."""

    integration_code = '''
# Add this to your depictio/cli/depictio_cli.py main() function

from rich import print
from rich.panel import Panel
from rich.text import Text
from rich.align import Align

# Depictio brand colors
DEPICTIO_COLORS = {
    "purple": "#9966CC", "violet": "#7A5DC7", "blue": "#6495ED",
    "teal": "#45B8AC", "green": "#8BC34A", "yellow": "#F9CB40",
    "orange": "#F68B33", "pink": "#E6779F", "red": "#E53935", "black": "#000000"
}

def create_depictio_logo():
    """Creates the Depictio logo with a unique color for each distinct triangle."""
    FAVICON_ASCII_FINAL = """
                                   .=AAAAABBBB=-:.
                                   .=AAAAAAAAAAA=-:.
                                   .=AAAAAAAAAAAAACCC=-
                                   .=AAAAAAAAAAAAAAAAA=-:.
                             .==.  .=AAAAAAAAAAAAAAAAAAAA-
                      .:-=+DDDD+:  .=AAAAAAAAAAAAAAAAAA-.
                   .-++DDDDDDDD+:  .=AAAAAAAAAAAAAAAA-.
                 .-+DDDDDDDDDDD+:  .=AAAAAAAAAAAAAA-.
                 .-+DDDDDDDDDDD+:  .=AAAAAAAAAAAA=.
                   .-+DDDDDDDDDD+:  .=AAAAAAAAAA-.  :=-.
                     .-+DDDDDDDD+:  .=AAAAAAAA=. .:=EEEE-.
                       .-+DDDDD+:  .=AAAAAA=.  .=EEEEEEE-.
                         .-+DDD+:  .=AAAA=.  :=EEEEEEEEEE-.
                   .=FGF-. .-+D+:  .=AA=.  .=GGGGGGGGGGGG=-:
                  .-HIIIIH-. .==:  .==:  .=GGGGGGGGGGGGGG=:.
                  .=JKKKKKKJ-:.        :=AAAAAAAAAAAAAAAAAAA
                   :-=------=-        .:--::::::::::::::::--

=============================-        :==+==================
LLLLLLLLLLLLLLLLLLLLLLLLLLL+:....   .. :+LLLLLLLLLLLLLLLLLLMM
DDDDDDDDDDDDDDDDDDDDDDDDDL+:. :NN-. .NO-. .+LLLLLLLLLLLLLLLD=-
DDDDDDDDDDDDDDDDDDDDDDDL+:  .+PQP:.  .PQQP-. .+LLLLLLLLLLLLD-:
:-LDDDDDDDDDDDDDDDDDDDL+:. .+PRRR:.  .PRRRRP-. :+LLLLLLLLLL+:.
:-+LDDDDDDDDDDDDDDDL+-. .+PSTSP:.  .PSTTTTP:.  :+LLLLLLD+-
  =DLDDDDDDDDDDDL+-. .+PUUVUUU:.  .PUUUUP=.     :+LLLUU-
  -+DLDDDDDDDDDL+-. .+PWWXWWWWU:.  .++-..          :=+=:
   :DULLDDDDLD-. .+PWWXXXXXWWU-
    .-DLDDLD-.   .=KXXXXDDDDDL-
      :=DD-.       .=DLLXXXKKL-
       .:.            .:=DLXXX-
"""

    # Each new character is mapped to a distinct brand color.
    color_map = {
        'A': DEPICTIO_COLORS['yellow'], 'B': DEPICTIO_COLORS['red'],
        'C': DEPICTIO_COLORS['pink'], 'D': DEPICTIO_COLORS['red'],
        'E': DEPICTIO_COLORS['yellow'], 'F': DEPICTIO_COLORS['purple'],
        'G': DEPICTIO_COLORS['yellow'], 'H': DEPICTIO_COLORS['purple'],
        'I': DEPICTIO_COLORS['blue'], 'J': DEPICTIO_COLORS['blue'],
        'K': DEPICTIO_COLORS['green'], 'L': DEPICTIO_COLORS['purple'],
        'M': DEPICTIO_COLORS['blue'], 'N': DEPICTIO_COLORS['red'],
        'O': DEPICTIO_COLORS['purple'], 'P': DEPICTIO_COLORS['blue'],
        'Q': DEPICTIO_COLORS['green'], 'R': DEPICTIO_COLORS['orange'],
        'S': DEPICTIO_COLORS['pink'], 'T': DEPICTIO_COLORS['yellow'],
        'U': DEPICTIO_COLORS['violet'], 'V': DEPICTIO_COLORS['teal'],
        'W': DEPICTIO_COLORS['green'], 'X': DEPICTIO_COLORS['orange'],
        '=': DEPICTIO_COLORS['teal'], '-': DEPICTIO_COLORS['green'],
        ':': DEPICTIO_COLORS['violet'], '.': DEPICTIO_COLORS['orange']
    }

    logo = Text()
    for line in FAVICON_ASCII_FINAL.split('\\n'):
        for char in line:
            if char in color_map:
                logo.append(char, style=f"{color_map[char]} bold")
            else:
                logo.append(char)
        logo.append('\\n')
    return logo

def main():
    # Assuming you have a function like this for polars if needed
    # add_rich_display_to_polars()

    # Create and display logo
    logo = create_depictio_logo()
    print(Panel.fit(
        Align.center(logo),
        border_style=DEPICTIO_COLORS['purple'],
        title="✨ Welcome to Depictio CLI ✨",
        title_align="center",
        padding=(1, 2)
    ))

    # Your existing app() call
    # app()
'''

    return integration_code

if __name__ == "__main__":
    demo_final_logo()

    print("\n" + "="*60)
    print("UPDATED INTEGRATION CODE:")
    print("="*60)
    print(get_cli_integration_code())