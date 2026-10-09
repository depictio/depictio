import { BASE_CHROME_STYLE } from 'depictio-react-core';
import type { ChromeStyle } from 'depictio-react-core';

import { GlassButton, GlassButtonGroup } from './Button';
import { glassPlotly, glassPlotlyDefaults } from './plotly';
import './glass.css';
import './glass-filters.css';

/**
 * Glass, the default chrome. The sidebar navigates, the dock acts; every
 * floating surface (sidebar, top bar, dock, drawers, the side panels) is
 * frosted glass over a quiet, flat tinted canvas, the palette stays neutral with
 * the instance's primary as the only accent, and the keys are springy pills.
 */
const style: ChromeStyle = {
  ...BASE_CHROME_STYLE,
  id: 'glass',
  name: 'Glass',
  tagline: 'Frosted panels over a calm canvas, with the actions in a dock',
  roles: {
    primary: { variant: 'filled', tone: 'primary' },
    secondary: { variant: 'light', tone: 'neutral' },
    quiet: { variant: 'subtle', tone: 'neutral' },
    toggle: { variant: 'subtle', tone: 'neutral', activeVariant: 'light', activeTone: 'primary' },
    danger: { variant: 'subtle', tone: 'danger' },
  },
  controlSize: 'sm',
  iconSize: 18,
  radius: 'xl',
  actionLabels: 'primary',
  layout: {
    // The top bar: the Analysis panel and the Guide start under it.
    headerHeight: 66,
    headerHeightMobile: 60,
    navbarWidth: 256,
    activeTabFilled: false,
  },
  plotly: glassPlotly,
  plotlyDefaults: glassPlotlyDefaults,
  components: {
    Button: GlassButton,
    ButtonGroup: GlassButtonGroup,
  },
};

export default style;
