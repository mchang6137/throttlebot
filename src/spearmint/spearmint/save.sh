cd ../bayOptSearch
dateTime=$(date +%Y%m%d_%H%M%S)
mkdir ~/Desktop/data/$dateTime
mv best_job_and_result.txt ~/Desktop/data/$dateTime
mv output ~/Desktop/data/$dateTime

rm -r jobs
rm -r output
rm best_job_and_result.txt
rm expt-grid.pkl
rm expt-grid.pkl.lock
rm trace.csv
rm chooser.GPEIOptChooser.pkl
rm chooser.GPEIOptChooser_hyperparameters.txt

if [ "$(ls -A ~/Desktop/data/$dateTime)" ];

then
    echo "Not Empty"
else
    rmdir ~/Desktop/data/$dateTime

fi

cd ../spearmint