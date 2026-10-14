// Paper Core excludes the PaperScript compiler (which requires unsafe-eval).
declare module 'paper/dist/paper-core' {
 import paper from 'paper';
 export default paper;
}
