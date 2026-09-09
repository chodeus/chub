"""CL2K poster maker — render a CL2K-style poster from a backdrop + clear logo.

Standalone render core (geometry + ImageMagick/Wand renderer), wired into Chub
as the ``cl2k_maker`` module. Nothing here imports the rest of the app, so it
can be exercised in isolation.
"""
