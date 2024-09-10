const handle_click = (n_clicks) => {
    if (n_clicks > 0) {
      return true;
    } else {
      return '';
    }
  };

  const handle_click_sidebar_width = (n_clicks, width) => {
    const current_width = parseInt(width.base)
    if (n_clicks > 0 & current_width == 300) {
     return {base: 70};
    } else {
      return {base:300};
    }
  }

  window.dash_clientside = { clientside: { handle_click, handle_click_sidebar_width }};