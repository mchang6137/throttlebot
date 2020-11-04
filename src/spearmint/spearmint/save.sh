cd /Users/rahulbalakrishnan/Desktop/throttlebot/src/spearmint/bayOptSearch
dateTime=$(date +%Y%m%d_%H%M%S)

toSave=$(ls -t ~/Desktop/data | head -1)


mkdir ~/Desktop/data/$toSave/$dateTime
mv best_job_and_result.txt ~/Desktop/data/$toSave/$dateTime
mv output ~/Desktop/data/$toSave/$dateTime

rm -r jobs
rm -r output
rm best_job_and_result.txt
rm expt-grid.pkl
rm expt-grid.pkl.lock
rm trace.csv
rm chooser.GPEIOptChooser.pkl
rm chooser.GPEIOptChooser_hyperparameters.txt

if [ "$(ls -A ~/Desktop/data/$toSave/$dateTime)" ];

then
    echo "Not Empty"
else
    rmdir ~/Desktop/data/$toSave/$dateTime

fi

cd /Users/rahulbalakrishnan/Desktop/throttlebot/src/spearmint/spearmint