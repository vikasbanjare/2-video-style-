// AutoEdit_Import.jsx — Premiere Pro (ExtendScript)
// Imports every edit in an autoedit output folder: the sequence XML and the
// captions SRT, then puts the SRT on a caption track of that sequence.
// Run with the ExtendScript Debugger in VS Code (target: Premiere Pro), or any
// script-runner panel. Manual alternative: File > Import the .xml, then drag the
// _captions.srt onto the sequence.

(function () {
    var root = Folder.selectDialog("Pick the autoedit output folder");
    if (!root) return;

    function findSequence(name) {
        for (var i = 0; i < app.project.sequences.numSequences; i++) {
            var s = app.project.sequences[i];
            if (s.name === name) return s;
        }
        return null;
    }

    function findItem(bin, name) {
        for (var i = 0; i < bin.children.numItems; i++) {
            var c = bin.children[i];
            if (c.name === name) return c;
            if (c.type === ProjectItemType.BIN) {
                var r = findItem(c, name);
                if (r) return r;
            }
        }
        return null;
    }

    var done = 0, log = [];
    var jobs = root.getFiles(function (f) { return f instanceof Folder; });
    for (var j = 0; j < jobs.length; j++) {
        var xmls = jobs[j].getFiles("*.xml");
        if (!xmls.length) continue;
        var stem = jobs[j].name;
        var before = app.project.sequences.numSequences;
        app.project.importFiles([xmls[0].fsName], true, app.project.rootItem, false);
        var seq = app.project.sequences.numSequences > before
            ? app.project.sequences[app.project.sequences.numSequences - 1] : null;
        if (!seq) { log.push(stem + ": XML import failed"); continue; }

        var srt = new File(jobs[j].fsName + "/" + stem + "_captions.srt");
        if (srt.exists) {
            app.project.importFiles([srt.fsName], true, app.project.rootItem, false);
            var item = findItem(app.project.rootItem, srt.name);
            if (item && seq.createCaptionTrack) {
                seq.createCaptionTrack(item, 0, Sequence.CAPTION_FORMAT_SUBTITLE);
            } else {
                log.push(stem + ": drag " + srt.name + " onto the sequence manually");
            }
        }
        done++;
    }
    alert("AutoEdit: imported " + done + " edit(s).\n" + log.join("\n") +
          "\n\nApply your saved caption Track Style to each caption track, review, export.");
})();
