"""Depictio bio-catalog package.

The catalog *data* (tool/module YAML files) lives alongside this module; the
catalog *models* + loaders live in
``depictio.models.components.advanced_viz.catalog`` (kept import-cheap). This
package hosts the heavier, render-time tooling that the model layer must not pull
in — currently :mod:`depictio.catalog.render` (the fixture render core behind
``depictio catalog preview`` and the demo docs embed).
"""
