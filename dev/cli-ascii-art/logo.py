
#!/usr/bin/env python3
"""
Depictio ASCII Art Logo Display

A rich console script to display the Depictio logo with colored ASCII art.
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

# Character to color mapping for the ASCII art
# Clockwise character order: * > + > _ > . > : > - > ~ > =
# Clockwise color order: violet > blue > orange > yellow > green > teal > pink > purple
ASCII_TO_COLOR = {
    '*': DEPICTIO_COLORS["violet"],    # 1st position (12 o'clock)
    '+': DEPICTIO_COLORS["blue"],      # 2nd position
    '_': DEPICTIO_COLORS["orange"],    # 3rd position
    '.': DEPICTIO_COLORS["yellow"],    # 4th position
    ':': DEPICTIO_COLORS["green"],     # 5th position
    '-': DEPICTIO_COLORS["teal"],      # 6th position
    '~': DEPICTIO_COLORS["pink"],      # 7th position
    '=': DEPICTIO_COLORS["purple"],    # 8th position
}


NAME_ASCII = """
                                                                                                                                                                                               
                                                                                                                                                                                             
  ███████████████████           ██████████████████████     ███████████████████       ███████           ██████████████       █████████████████████████   ██████            ██████████████       
  █████████████████████         ██████████████████████     █████████████████████     ███████         ██████████████████     █████████████████████████   ██████         ███████████████████     
  ███████████████████████       ██████████████████████     ██████████████████████    ███████       ██████████████████████   ████████████████████████    ██████       ███████████████████████   
                  ████████      ███████                    ██████          ███████   ███████      ████████        ████████           ███████            ██████      █████████        █████████ 
                    ███████     ███████                    ██████           ██████   ███████     ███████            ███████          ███████            ██████     ███████             ████████
                     ███████    ███████                    ██████           ██████   ███████    ███████              ██████          ███████            ██████    ███████               ███████
                     ███████    █████████████████████      ██████          ███████   ███████    ██████                               ███████            ██████    ███████                ██████
                      ██████    █████████████████████      ██████████████████████    ███████    ██████                               ███████            ██████    ██████                 ██████
                     ███████    █████████████████████      █████████████████████     ███████    ██████                               ███████            ██████    ███████                ██████
                     ███████    ███████                    ██████████████████        ███████    ███████               ████           ███████            ██████    ███████               ███████
                    ███████     ███████                    ██████                    ███████     ███████            ███████          ███████            ██████     ███████             ████████
                 █████████      ███████                    ██████                    ███████     █████████        █████████          ███████            ██████      ████████         █████████ 
  ███████████████████████       ██████████████████████     ██████                    ███████       ██████████████████████            ███████            ██████       ███████████████████████   
  █████████████████████         ██████████████████████     ██████                    ███████        ████████████████████             ███████            ██████         ████████████████████    
  ███████████████████           ██████████████████████     ██████                     ██████           ██████████████                 █████             ██████           ███████████████       
                                                                                                                                                                                               
"""



# The ASCII art has been updated to use a unique character for each visually distinct triangle.
FAVICON_ASCII_FINAL = """
                                                        *******
                                                        ***********                                
                                                       ****************                            
                                                       ********************                       
                                                       ***********************                   
                                                       **************************                  
                                                       ****************************               
                                                       ******************************             
                                                       *********************************            
                                        ==========     *******************************              
                                   ===============     *****************************                
                                ==================     ****************************                 
                             =====================     **************************                   
                            ======================     ************************                     
                             =====================     **********************                       
                              ====================     ********************                         
                                ==================     ******************        ++                 
                                  ================     *****************       +++++                
                                    ==============     ***************       +++++++++              
                                      ============     ************         +++++++++++             
                                        ==========     ***********       +++++++++++++++            
                                          ========     *********       ++++++++++++++++++           
                                 ~~~       =======     *******       +++++++++++++++++++++          
                                ~~~~~~       =====     *****        ++++++++++++++++++++++          
                               ~~~~~~~~~       ===     ***        +++++++++++++++++++++++++         
                              ~~~~~~~~~~~~      ==              +++++++++++++++++++++++++++         
                             ~~~~~~~~~~~~~~~     =            +++++++++++++++++++++++++++++         
                             ~~~~~~~~~~~~~~~~               +++++++++++++++++++++++++++++++         
                                                                                                    
                                                                                                    
                                                                                                    
---------------------------------------------               ________________________________        
-------------------------------------------                   ______________________________        
------------------------------------------                      ___________________________         
----------------------------------------       :::     ...        _________________________         
 -------------------------------------       :::::     .....        _______________________         
 -----------------------------------       :::::::     .......       _____________________          
 ---------------------------------        ::::::::     .........       ___________________          
  -------------------------------       ::::::::::     ...........       ________________           
  -----------------------------       ::::::::::::     ............        _____________            
   --------------------------       ::::::::::::::     .............         __________             
    -----------------------       ::::::::::::::::     ..............          ______               
     --------------------        :::::::::::::::::                              ____                
      -----------------        :::::::::::::::::::                                                  
       --------------        :::::::::::::::::::::                                                  
        -----------         ::::::::::::::::::::::                                                  
          -------             ::::::::::::::::::::                                                  
           -----                 :::::::::::::::::                                                  
                                    ::::::::::::::                                                  
                                         :::::::::                                           
"""


def scale_ascii_art(ascii_art: str, scale: float = 1.0) -> str:
    """Scale ASCII art by removing lines and characters based on scale factor.
    
    Args:
        ascii_art: The original ASCII art string
        scale: Scale factor (0.5 = half size, 0.25 = quarter size, etc.)
    
    Returns:
        Scaled ASCII art string
    """
    if scale >= 1.0:
        return ascii_art
    
    lines = ascii_art.split('\n')
    
    # Skip lines based on scale factor
    line_step = max(1, int(1 / scale))
    scaled_lines = lines[::line_step]
    
    # Skip characters within each line based on scale factor
    char_step = max(1, int(1 / scale))
    scaled_art_lines = []
    
    for line in scaled_lines:
        if scale <= 0.5:
            # For very small scales, take every nth character
            scaled_line = line[::char_step]
        else:
            # For moderate scaling, just use line scaling
            scaled_line = line
        scaled_art_lines.append(scaled_line)
    
    return '\n'.join(scaled_art_lines)


def create_colored_logo(size: str = "full") -> Text:
    """Create a colored version of the Depictio ASCII logo using Rich.
    
    Args:
        size: Logo size - "full", "large" (0.75), "medium" (0.5), "small" (0.33), or "tiny" (0.25)
    
    Returns:
        Rich Text object with colored logo
    """
    # Size presets
    size_scales = {
        "full": 1.0,
        "large": 0.75,
        "medium": 0.5,
        "small": 0.33,
        "tiny": 0.25
    }
    
    # Get scale factor
    if isinstance(size, str):
        scale = size_scales.get(size.lower(), 1.0)
    else:
        scale = float(size)
    
    # Scale the ASCII art
    scaled_art = scale_ascii_art(FAVICON_ASCII_FINAL, scale)
    
    logo_text = Text()
    
    for line in scaled_art.split('\n'):
        line_text = Text()
        for char in line:
            if char in ASCII_TO_COLOR:
                # Apply color to the character
                line_text.append(char, style=ASCII_TO_COLOR[char])
            else:
                # Keep spaces and other characters as default
                line_text.append(char)
        line_text.append('\n')
        logo_text.append_text(line_text)
    
    return logo_text


def display_logo(console: Console = None, with_panel: bool = True, title: str = "🎨 DEPICTIO", 
                 size: str = "full") -> None:
    """Display the Depictio logo with optional panel and title.
    
    Args:
        console: Rich console instance
        with_panel: Whether to display with a panel border
        title: Panel title text
        size: Logo size - "full", "large", "medium", "small", "tiny", or float scale factor
    """
    if console is None:
        console = Console()
    
    logo = create_colored_logo(size)
    
    if with_panel:
        # Display with a panel border
        panel = Panel(
            Align.center(logo),
            title=title,
            title_align="center",
            border_style="bright_blue",
            padding=(1, 2)
        )
        console.print(panel)
    else:
        # Display without panel, centered
        console.print(Align.center(logo))


def main():
    """Main function to display the logo."""
    import sys
    
    console = Console()
    
    # Parse command line arguments
    size = "full"
    show_sizes = False
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--sizes":
            show_sizes = True
        elif sys.argv[1] in ["full", "large", "medium", "small", "tiny"]:
            size = sys.argv[1]
        else:
            try:
                size = float(sys.argv[1])
            except ValueError:
                console.print("Invalid size. Use: full, large, medium, small, tiny, or a float value", style="red")
                return
    
    if show_sizes:
        # Demonstrate all sizes
        sizes = ["full", "large", "medium", "small", "tiny"]
        for s in sizes:
            console.print(f"\n[bold]Size: {s}[/bold]")
            display_logo(console, with_panel=False, size=s)
            console.print("-" * 60)
    else:
        # Display single logo
        display_logo(console, with_panel=True, size=size)
        
        # Add a subtitle
        subtitle = Text("Data Visualization & Analytics Platform", style="italic dim")
        console.print(Align.center(subtitle))
        console.print()


def print_usage():
    """Print usage information."""
    console = Console()
    console.print("""
[bold]Depictio ASCII Logo Display[/bold]

Usage:
    python logo.py [size]
    python logo.py --sizes

Arguments:
    size        Logo size: full, large, medium, small, tiny, or float value (e.g., 0.3)
    --sizes     Show all size options

Examples:
    python logo.py           # Full size logo
    python logo.py medium    # Medium size logo
    python logo.py 0.3       # Custom 30% scale
    python logo.py --sizes   # Show all sizes
    """)


if __name__ == "__main__":
    main()
