const path = require('path');
const packageJson = require('./package.json');

const libraryName = packageJson.name.replace(/-/g, '_');

module.exports = (env, argv) => {
  const mode = argv.mode || 'production';
  return {
    mode,
    entry: './src/lib/index.ts',
    output: {
      path: path.resolve(__dirname, 'depictio_components'),
      filename:
        mode === 'development'
          ? `${libraryName}.dev.js`
          : `${libraryName}.min.js`,
      library: libraryName,
      libraryTarget: 'window',
    },
    externals: {
      react: 'React',
      'react-dom': 'ReactDOM',
      'plotly.js': 'Plotly',
    },
    module: {
      rules: [
        {
          test: /\.(ts|tsx|js|jsx)$/,
          exclude: /node_modules/,
          use: {
            loader: 'babel-loader',
            options: {
              presets: [
                '@babel/preset-env',
                '@babel/preset-react',
                '@babel/preset-typescript',
              ],
            },
          },
        },
        {
          test: /\.css$/,
          use: ['style-loader', 'css-loader'],
        },
      ],
    },
    resolve: {
      extensions: ['.ts', '.tsx', '.js', '.jsx'],
    },
    devtool: mode === 'development' ? 'source-map' : false,
  };
};
