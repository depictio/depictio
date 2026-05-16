/**
 * Dispatcher for the per-type builder form. Same component is mounted in
 * stepper step 3 (create flow) and the EditComponentPage (edit flow), so
 * UI is guaranteed identical between create and edit.
 */
import React from 'react';
import { Alert } from '@mantine/core';
import { useBuilderStore } from './store/useBuilderStore';
import CardBuilder from './card/CardBuilder';
import FigureBuilder from './figure/FigureBuilder';
import InteractiveBuilder from './interactive/InteractiveBuilder';
import TableBuilder from './table/TableBuilder';
import MultiQCBuilder from './multiqc/MultiQCBuilder';
import ImageBuilder from './image/ImageBuilder';
import MapBuilder from './map/MapBuilder';
import AdvancedVizBuilder from './advanced_viz/AdvancedVizBuilder';

const ComponentBuilder: React.FC = () => {
  const componentType = useBuilderStore((s) => s.componentType);

  switch (componentType) {
    case 'card':
      return <CardBuilder />;
    case 'figure':
      return <FigureBuilder />;
    case 'interactive':
      return <InteractiveBuilder />;
    case 'table':
      return <TableBuilder />;
    case 'multiqc':
      return <MultiQCBuilder />;
    case 'image':
      return <ImageBuilder />;
    case 'map':
      return <MapBuilder />;
    case 'advanced_viz':
      return <AdvancedVizBuilder />;
    default:
      return (
        <Alert color="yellow" title="Unknown component type">
          {String(componentType)}
        </Alert>
      );
  }
};

export default ComponentBuilder;
