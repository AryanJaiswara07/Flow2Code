"""Flow2Code — turn a flowchart into a runnable Python program.

The package is deliberately UI-free: nothing in here imports tkinter, cv2 or a web
framework, so the whole generator can be tested headlessly with pytest.

    from flow2code.loader import load_flowchart
    from flow2code.graph import build, validate
    from flow2code.codegen import generate

    fc = load_flowchart("samples/even_odd.flow.json")
    g = build(fc)
    validate(fc, g)                  # raises Flow2CodeError with a clear message
    print(generate(fc, g))           # the Python program
"""
from .models import Edge, Flowchart, Node, NODE_TYPES  # noqa: F401

__version__ = "0.1 (prototype)"
__all__ = ["Edge", "Flowchart", "Node", "NODE_TYPES", "__version__"]
