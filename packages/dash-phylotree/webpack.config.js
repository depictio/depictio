const path = require('path');

module.exports = {
    entry: './src/lib/index.js',
    output: {
        path: path.resolve(__dirname, 'dash_phylotree'),
        filename: 'dash_phylotree.min.js',
        library: {
            name: 'dash_phylotree',
            type: 'window',
        },
    },
    externals: {
        react: 'React',
        'react-dom': 'ReactDOM',
    },
    module: {
        rules: [
            {
                test: /\.jsx?$/,
                exclude: /node_modules\/(?!react-phylogeny-tree|@mkoliba)/,
                use: {
                    loader: 'babel-loader',
                },
            },
            {
                test: /\.css$/,
                use: ['style-loader', 'css-loader'],
            },
        ],
    },
    resolve: {
        extensions: ['.js', '.jsx', '.ts', '.tsx'],
    },
};
